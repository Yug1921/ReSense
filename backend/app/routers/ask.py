"""
Track C — POST /ask

Scoped strictly to one paper: retrieves the most relevant chunks of
*that paper only* (via BM25, Track C's chunking/retrieval services)
plus a bounded slice of *that paper's* recent chat history, and asks
OpenRouter to answer from those excerpts alone. Every turn is persisted
to chat_messages so a reload replays the full conversation instead of
losing it.
"""
from fastapi import APIRouter, HTTPException
import re

from app.db.supabase_client import get_supabase, PAPERS_TABLE, CHAT_MESSAGES_TABLE, FIGURES_TABLE
from app.services.figures_data import ensure_figures_captioned
from app.models.schemas import AskRequest, AskResponse
from app.services.chunking import chunk_paper
from app.services.retrieval import retrieve_relevant_chunks
from app.services.llm import call_openrouter, LLMRateLimitError, LLMRequestError
from app.services.prompts import build_ask_prompt

router = APIRouter(tags=["ask"])

_TOP_K_CHUNKS = 6  # larger papers have more relevant sections to draw from
_MAX_HISTORY_TURNS = 6  # keeps the context window bounded to recent turns


def _local_fallback_answer(question: str, relevant_chunks: list[dict]) -> str:
    """Return grounded excerpts when all remote providers are temporarily busy."""
    question_terms = {
        term.lower() for term in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", question)
    }
    ranked = sorted(
        relevant_chunks,
        key=lambda chunk: sum(
            term in chunk["text"].lower() for term in question_terms
        ),
        reverse=True,
    )
    excerpts = []
    for chunk in ranked[:2]:
        text = " ".join(chunk["text"].split())
        if text:
            excerpts.append(f"[{chunk['section']}] {text[:700]}")
    if not excerpts:
        return "I could not find a relevant passage in this paper."
    return (
        "The AI providers are temporarily busy, so here are the most relevant "
        "paper passages for your question:\n\n" + "\n\n".join(excerpts)
    )


@router.post("/ask", response_model=AskResponse)
async def ask_paper(req: AskRequest) -> AskResponse:
    question = req.question.strip()
    if len(question) < 3:
        # Graceful nudge instead of spending an LLM call on junk input
        # (reliability checklist: "empty/garbage question").
        return AskResponse(
            paper_id=req.paper_id,
            answer="Could you ask something a bit more specific about the paper?",
            used_sections=[],
        )

    supabase = get_supabase()

    paper_result = (
        supabase.table(PAPERS_TABLE).select("*").eq("id", req.paper_id).limit(1).execute()
    )
    if not paper_result.data:
        raise HTTPException(status_code=404, detail="No paper found for this paper_id.")
    paper = paper_result.data[0]

    if paper["status"] != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Paper is not ready for Q&A (status: {paper['status']}).",
        )

    history_result = (
        supabase.table(CHAT_MESSAGES_TABLE)
        .select("role, content")
        .eq("paper_id", req.paper_id)
        .order("created_at", desc=True)
        .limit(_MAX_HISTORY_TURNS)
        .execute()
    )
    # DB gave us newest-first; flip back to chronological order for the prompt.
    chat_history = list(reversed(history_result.data))

    figures = await ensure_figures_captioned(supabase, FIGURES_TABLE, req.paper_id)
    tables = (paper.get("structure_json") or {}).get("tables", [])
    extra_chunks = [
        {"section": f"{(f.get('image_type') or 'figure').capitalize()} on page {f['page_number']}", "text": f["caption"]}
        for f in figures
    ] + [
        {"section": f"Table on page {t['page_number']}", "text": t["content"]}
        for t in tables
    ]
    chunks = chunk_paper(paper["raw_text"], paper.get("structure_json"), extra_chunks=extra_chunks)
    relevant_chunks = retrieve_relevant_chunks(question, chunks, top_k=_TOP_K_CHUNKS)
    preamble_chunks = [c for c in chunks if c["section"].lower() == "preamble"]
    for chunk in preamble_chunks:
        if chunk not in relevant_chunks:
            relevant_chunks = [chunk] + relevant_chunks

    system_prompt, user_prompt = build_ask_prompt(question, relevant_chunks, chat_history)

    try:
        answer = await call_openrouter(system_prompt, user_prompt, max_tokens=500)
    except LLMRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except LLMRequestError as exc:
        answer = _local_fallback_answer(question, relevant_chunks)

    # Persist both turns so a reload restores the full conversation.
    supabase.table(CHAT_MESSAGES_TABLE).insert(
        [
            {"paper_id": req.paper_id, "role": "user", "content": question},
            {"paper_id": req.paper_id, "role": "assistant", "content": answer},
        ]
    ).execute()

    used_sections = sorted({c["section"] for c in relevant_chunks})
    return AskResponse(paper_id=req.paper_id, answer=answer, used_sections=used_sections)