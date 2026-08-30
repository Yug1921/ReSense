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
from app.services.figure_storage import download_figure_image
from app.services.vision import call_vision_model
from app.services.vision_prompts import build_vision_prompt, parse_vision_response

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

    figures_result = (
        supabase.table(FIGURES_TABLE)
        .select("*")
        .eq("paper_id", req.paper_id)
        .order("page_number")
        .execute()
    )
    rows = figures_result.data
    all_cached = True

    for row in rows:
        if row.get("caption"):
            continue  # already captioned in a previous call

        all_cached = False
        try:
            image_bytes = download_figure_image(row["storage_path"])
            extension = row["storage_path"].rsplit(".", 1)[-1]
            system_prompt, user_text = build_vision_prompt(row["page_number"])
            raw_response = await call_vision_model(system_prompt, user_text, image_bytes, extension)
            image_type, caption = parse_vision_response(raw_response)

            supabase.table(FIGURES_TABLE).update(
                {"image_type": image_type, "caption": caption}
            ).eq("id", row["id"]).execute()
            row["image_type"] = image_type
            row["caption"] = caption
        except Exception:
            # One bad/uncaptionable image should never fail the whole
            # request — leave it uncaptioned and move on to the rest.
            continue

    return FiguresResponse(
        paper_id=req.paper_id,
        figures=[Figure(**row) for row in rows],
        cached=all_cached,
    )