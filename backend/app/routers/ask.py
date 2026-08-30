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

from app.db.supabase_client import get_supabase, PAPERS_TABLE, CHAT_MESSAGES_TABLE, FIGURES_TABLE
from app.models.schemas import AskRequest, AskResponse
from app.services.chunking import chunk_paper
from app.services.retrieval import retrieve_relevant_chunks
from app.services.llm import call_openrouter, LLMRateLimitError, LLMRequestError
from app.services.prompts import build_ask_prompt

router = APIRouter(tags=["ask"])

_TOP_K_CHUNKS = 4
_MAX_HISTORY_TURNS = 6  # keeps the context window bounded to recent turns


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

    chunks = chunk_paper(paper["raw_text"], paper.get("structure_json"), figures=_fetch_captioned_figures(supabase, req.paper_id))
    relevant_chunks = retrieve_relevant_chunks(question, chunks, top_k=_TOP_K_CHUNKS)

    system_prompt, user_prompt = build_ask_prompt(question, relevant_chunks, chat_history)

    try:
        answer = await call_openrouter(system_prompt, user_prompt, max_tokens=500)
    except LLMRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except LLMRequestError as exc:
        raise HTTPException(
            status_code=502, detail=f"The Q&A assistant is unavailable right now: {exc}"
        ) from exc

    # Persist both turns so a reload restores the full conversation.
    supabase.table(CHAT_MESSAGES_TABLE).insert(
        [
            {"paper_id": req.paper_id, "role": "user", "content": question},
            {"paper_id": req.paper_id, "role": "assistant", "content": answer},
        ]
    ).execute()

    used_sections = sorted({c["section"] for c in relevant_chunks})
    return AskResponse(paper_id=req.paper_id, answer=answer, used_sections=used_sections)

def _fetch_captioned_figures(supabase, paper_id: str) -> list[dict]:
    """Only figures that already have a caption are useful as retrieval
    context — an uncaptioned figure (never run through /figures yet) has
    nothing to search over."""
    result = (
        supabase.table(FIGURES_TABLE)
        .select("page_number, image_type, caption")
        .eq("paper_id", paper_id)
        .not_.is_("caption", "null")
        .execute()
    )
    return result.data