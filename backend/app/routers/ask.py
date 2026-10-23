"""
Track C — POST /ask

Scoped strictly to one paper: retrieves the most relevant chunks of
*that paper only* (via BM25, Track C's chunking/retrieval services)
plus a bounded slice of *that paper's* recent chat history, and asks
OpenRouter to answer from those excerpts alone. Every turn is persisted
to chat_messages so a reload replays the full conversation instead of
losing it.
"""
from fastapi import APIRouter, HTTPException, Depends
import re

from app.db.supabase_client import get_supabase, PAPERS_TABLE, CHAT_MESSAGES_TABLE, FIGURES_TABLE
from app.services.figures_data import ensure_figures_captioned
from app.models.schemas import AskRequest, AskResponse
from app.services.chunking import chunk_paper, paper_outline
from app.services.parser import detect_structure
from app.services.retrieval import retrieve_relevant_chunks
from app.services.llm import call_openrouter, LLMRateLimitError, LLMRequestError
from app.services.prompts import build_ask_prompt, build_ask_full_paper_prompt

from app.auth import CurrentUser, current_user

router = APIRouter(tags=["ask"])

_TOP_K_CHUNKS = 10  # about 1,800 words: room for a broad answer, still fits Groq's free limit
_MAX_HISTORY_TURNS = 6  # keeps the context window bounded to recent turns


def _figure_label(figure: dict) -> str:
    """'Table 3' from the caption when known, else 'Figure on page 4'."""
    named = re.match(r"\s*((?:fig(?:ure)?\.?|table)\s*\d+)", figure.get("caption") or "", re.IGNORECASE)
    if named:
        return re.sub(r"^fig\.?\s*", "Figure ", named.group(1), flags=re.IGNORECASE).strip().capitalize()
    kind = (figure.get("image_type") or "figure").capitalize()
    return f"{kind} on page {figure['page_number']}" if figure.get("page_number") else kind


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
async def ask_paper(req: AskRequest, user: CurrentUser = Depends(current_user)) -> AskResponse:
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
        supabase.table(PAPERS_TABLE)
        .select("*")
        .eq("id", req.paper_id)
        .eq("user_id", user.id)
        .limit(1)
        .execute()
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
        {"section": _figure_label(f), "text": f["caption"]}
        for f in figures
    ] + [
        {"section": f"Table on page {t['page_number']}", "text": t["content"]}
        for t in tables
    ]
    chunks = chunk_paper(paper["raw_text"], paper.get("structure_json"), extra_chunks=extra_chunks)
    previous_question = next(
        (turn["content"] for turn in reversed(chat_history) if turn["role"] == "user"), ""
    )
    relevant_chunks = retrieve_relevant_chunks(
        question, chunks, top_k=_TOP_K_CHUNKS, context=previous_question
    )
    outline = paper_outline(paper["raw_text"])
    title = paper.get("filename") or ""
    system_prompt, user_prompt = build_ask_prompt(
        question, relevant_chunks, chat_history, outline=outline, title=title
    )
    # Long-context models (Gemini) read the whole paper, like pasting it into a chat.
    _, full_prompt = build_ask_full_paper_prompt(
        question,
        detect_structure(paper["raw_text"])["sections"],
        chat_history,
        outline=outline,
        title=title,
        extras=extra_chunks,
    )

    try:
        answer = await call_openrouter(
            system_prompt,
            user_prompt,
            max_tokens=1500,
            temperature=0.2,
            long_context_user_prompt=full_prompt,
        )
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

    # Most relevant first, each section once.
    used_sections = list(dict.fromkeys(c["section"] for c in relevant_chunks))[:5]
    return AskResponse(paper_id=req.paper_id, answer=answer, used_sections=used_sections)