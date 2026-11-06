"""
Track B — POST /summarize

Given a paper_id and a tone, return a cached summary if one already
exists for that (paper_id, tone) pair; otherwise generate one via
OpenRouter and cache it. This caching is what makes switching tones in
the UI free after the first generation per tone.
"""
import asyncio

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import Response

from app.db.supabase_client import get_supabase, PAPERS_TABLE, SUMMARIES_TABLE
from app.db.supabase_client import FIGURES_TABLE
from app.models.schemas import SummarizeRequest, SummarizeResponse
from app.services.llm import call_openrouter, LLMRateLimitError, LLMRequestError
from app.services.prompts import (
    build_summary_prompt,
    build_figure_table_prompt,
    normalize_figure_table_response,
)
from app.services.figures_data import ensure_figures_captioned
from app.services.export import download_name, summary_docx, summary_pdf

from app.auth import CurrentUser, current_user

router = APIRouter(tags=["summarize"])

_VALID_TONES = {"academic", "technical", "research_insight", "figure_table_analysis", "critical_review"}
_SUPABASE_TIMEOUT_SECONDS = 10


async def _execute_query(query):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(query.execute), timeout=_SUPABASE_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="The paper database did not respond in time. Please try again.",
        ) from exc


@router.post("/summarize", response_model=SummarizeResponse)
async def summarize_paper(
    req: SummarizeRequest, user: CurrentUser = Depends(current_user)
) -> SummarizeResponse:
    if req.tone not in _VALID_TONES:
        raise HTTPException(
            status_code=400,
            detail=f"tone must be one of {sorted(_VALID_TONES)}",
        )

    supabase = get_supabase()

    paper_query = (
        supabase.table(PAPERS_TABLE).select("*").eq("id", req.paper_id).eq("user_id", user.id).limit(1)
    )
    paper_result = await _execute_query(paper_query)
    if not paper_result.data:
        raise HTTPException(status_code=404, detail="No paper found for this paper_id.")
    paper = paper_result.data[0]

    if paper["status"] != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Paper is not ready for summarization (status: {paper['status']}).",
        )

    # Cache check — this is the "zero extra LLM calls on tone re-visit" behavior.
    cached_query = (
        supabase.table(SUMMARIES_TABLE)
        .select("*")
        .eq("paper_id", req.paper_id)
        .eq("tone", req.tone)
        .limit(1)
    )
    cached = await _execute_query(cached_query)
    if cached.data and not req.refresh:
        return SummarizeResponse(
            paper_id=req.paper_id, tone=req.tone, content=cached.data[0]["content"], cached=True
        )

    if req.tone == "figure_table_analysis":
        figures = await ensure_figures_captioned(supabase, FIGURES_TABLE, req.paper_id)
        tables = (paper.get("structure_json") or {}).get("tables", [])
        system_prompt, user_prompt = build_figure_table_prompt(
            figures, tables, paper_context=paper.get("raw_text") or ""
        )
    else:
        system_prompt, user_prompt = build_summary_prompt(req.tone, paper["raw_text"])

    try:
        content = await call_openrouter(system_prompt, user_prompt, max_tokens=2200)
    except LLMRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except LLMRequestError as exc:
        raise HTTPException(
            status_code=502, detail=f"The summarization assistant is unavailable right now: {exc}"
        ) from exc

    if req.tone == "figure_table_analysis":
        content = normalize_figure_table_response(content, figures, tables)

    summary_data = {"paper_id": req.paper_id, "tone": req.tone, "content": content}
    if cached.data:
        save_query = (
            supabase.table(SUMMARIES_TABLE)
            .update({"content": content})
            .eq("paper_id", req.paper_id)
            .eq("tone", req.tone)
        )
    else:
        save_query = supabase.table(SUMMARIES_TABLE).insert(summary_data)
    await _execute_query(save_query)

    return SummarizeResponse(paper_id=req.paper_id, tone=req.tone, content=content, cached=False)


_DOWNLOAD_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.get("/summarize/{paper_id}/{tone}/download")
async def download_summary(
    paper_id: str,
    tone: str,
    format: str = Query("pdf", pattern="^(pdf|docx)$"),
    user: CurrentUser = Depends(current_user),
) -> Response:
    """The saved summary in this tone as a formatted PDF or Word file."""
    if tone not in _VALID_TONES:
        raise HTTPException(status_code=400, detail=f"tone must be one of {sorted(_VALID_TONES)}")
    supabase = get_supabase()
    paper_result = await _execute_query(
        supabase.table(PAPERS_TABLE).select("id, filename").eq("id", paper_id).eq("user_id", user.id).limit(1)
    )
    if not paper_result.data:
        raise HTTPException(status_code=404, detail="No paper found for this paper_id.")
    summary_result = await _execute_query(
        supabase.table(SUMMARIES_TABLE).select("content").eq("paper_id", paper_id).eq("tone", tone).limit(1)
    )
    if not summary_result.data:
        raise HTTPException(status_code=404, detail="Write this summary first, then download it.")

    filename = paper_result.data[0].get("filename") or "paper"
    content = summary_result.data[0]["content"]
    build = summary_pdf if format == "pdf" else summary_docx
    body = await asyncio.to_thread(build, filename, tone, content)
    return Response(
        content=body,
        media_type=_DOWNLOAD_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{download_name(filename, tone, format)}"'},
    )
