"""
Track J (Vision) — POST /figures

Read + on-demand caption. Image extraction already happened at upload
time (cheap, no LLM cost); this endpoint is where the actual vision
model gets called, and only for figures that don't have a caption yet —
so re-calling this endpoint after the first successful pass costs zero
additional vision calls, same caching philosophy as /summarize and
/analyze.

Deliberately reuses AnalyzeRequest ({paper_id}) as the request body
shape — no new request model needed for a single-field payload.
"""
from fastapi import APIRouter, HTTPException

from app.db.supabase_client import get_supabase, PAPERS_TABLE, FIGURES_TABLE
from app.models.schemas import AnalyzeRequest, FiguresResponse, Figure
from app.services.figures_data import ensure_figures_captioned

router = APIRouter(tags=["figures"])


@router.post("/figures", response_model=FiguresResponse)
async def get_figures(req: AnalyzeRequest) -> FiguresResponse:
    supabase = get_supabase()

    paper_result = (
        supabase.table(PAPERS_TABLE).select("id, status").eq("id", req.paper_id).limit(1).execute()
    )
    if not paper_result.data:
        raise HTTPException(status_code=404, detail="No paper found for this paper_id.")
    if paper_result.data[0]["status"] != "ready":
        raise HTTPException(status_code=409, detail="Paper is not ready.")

    rows = await ensure_figures_captioned(supabase, FIGURES_TABLE, req.paper_id)
    all_cached = True

    return FiguresResponse(
        paper_id=req.paper_id,
        figures=[Figure(**row) for row in rows],
        cached=all_cached,
    )