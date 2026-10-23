"""
The signed-in user's library: list their papers, or remove one.

Listing reads only light columns (never raw_text) so the home page stays fast
however long the papers are.
"""
from fastapi import APIRouter, Depends, HTTPException, Response

from app.auth import CurrentUser, current_user
from app.db.supabase_client import get_supabase, PAPERS_TABLE, FIGURES_TABLE, FIGURES_BUCKET
from app.models.schemas import PaperListItem

router = APIRouter(tags=["papers"])


@router.get("/papers", response_model=list[PaperListItem])
async def list_papers(user: CurrentUser = Depends(current_user)) -> list[PaperListItem]:
    supabase = get_supabase()
    result = (
        supabase.table(PAPERS_TABLE)
        .select("id, filename, status, uploaded_at, word_count:structure_json->word_count")
        .eq("user_id", user.id)
        .order("uploaded_at", desc=True)
        .execute()
    )
    return [
        PaperListItem(
            paper_id=row["id"],
            filename=row["filename"],
            status=row["status"],
            uploaded_at=row["uploaded_at"],
            word_count=row.get("word_count"),
        )
        for row in result.data
    ]


@router.delete("/papers/{paper_id}", status_code=204)
async def delete_paper(paper_id: str, user: CurrentUser = Depends(current_user)) -> Response:
    supabase = get_supabase()
    owned = (
        supabase.table(PAPERS_TABLE).select("id").eq("id", paper_id).eq("user_id", user.id).limit(1).execute()
    )
    if not owned.data:
        raise HTTPException(status_code=404, detail="No paper found for this paper_id.")

    # Figure images live in Storage, outside the database cascade.
    figures = supabase.table(FIGURES_TABLE).select("storage_path").eq("paper_id", paper_id).execute()
    paths = [row["storage_path"] for row in figures.data if row.get("storage_path")]
    if paths:
        try:
            supabase.storage.from_(FIGURES_BUCKET).remove(paths)
        except Exception:
            pass  # Orphaned images are harmless; never block the delete on them.

    # summaries, analysis, chat, figures and integrity rows go with it (on delete cascade).
    supabase.table(PAPERS_TABLE).delete().eq("id", paper_id).eq("user_id", user.id).execute()
    return Response(status_code=204)
