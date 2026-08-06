"""
Track B — POST /summarize

Given a paper_id and a tone, return a cached summary if one already
exists for that (paper_id, tone) pair; otherwise generate one via
OpenRouter and cache it. This caching is what makes switching tones in
the UI free after the first generation per tone.
"""
from fastapi import APIRouter, HTTPException

from app.db.supabase_client import get_supabase, PAPERS_TABLE, SUMMARIES_TABLE
from app.models.schemas import SummarizeRequest, SummarizeResponse
from app.services.llm import call_openrouter, LLMRateLimitError, LLMRequestError
from app.services.prompts import build_summary_prompt

router = APIRouter(tags=["summarize"])

_VALID_TONES = {"simple", "technical", "connect"}


@router.post("/summarize", response_model=SummarizeResponse)
async def summarize_paper(req: SummarizeRequest) -> SummarizeResponse:
    if req.tone not in _VALID_TONES:
        raise HTTPException(
            status_code=400,
            detail=f"tone must be one of {sorted(_VALID_TONES)}",
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
            detail=f"Paper is not ready for summarization (status: {paper['status']}).",
        )

    # Cache check — this is the "zero extra LLM calls on tone re-visit" behavior.
    cached = (
        supabase.table(SUMMARIES_TABLE)
        .select("*")
        .eq("paper_id", req.paper_id)
        .eq("tone", req.tone)
        .limit(1)
        .execute()
    )
    if cached.data:
        return SummarizeResponse(
            paper_id=req.paper_id, tone=req.tone, content=cached.data[0]["content"], cached=True
        )

    system_prompt, user_prompt = build_summary_prompt(req.tone, paper["raw_text"])

    try:
        content = await call_openrouter(system_prompt, user_prompt)
    except LLMRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except LLMRequestError as exc:
        raise HTTPException(
            status_code=502, detail=f"The summarization assistant is unavailable right now: {exc}"
        ) from exc

    supabase.table(SUMMARIES_TABLE).insert(
        {"paper_id": req.paper_id, "tone": req.tone, "content": content}
    ).execute()

    return SummarizeResponse(paper_id=req.paper_id, tone=req.tone, content=content, cached=False)
