"""POST /integrity/references — deterministic Crossref reference checking."""

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.db.supabase_client import INTEGRITY_TABLE, PAPERS_TABLE, get_supabase
from app.models.schemas import (
    ReferenceCheckRequest,
    ReferenceCheckResponse,
    ReferenceItem,
)
from app.services.references import extract_references, verify_all


router = APIRouter(prefix="/integrity", tags=["integrity"])


def _build_response(paper_id: str, items: list[dict], cached: bool) -> ReferenceCheckResponse:
    counts = {
        "verified": sum(item["status"] == "verified" for item in items),
        "uncertain": sum(item["status"] == "uncertain" for item in items),
        "not_found": sum(item["status"] == "not_found" for item in items),
        "unavailable": sum(item["status"] == "unavailable" for item in items),
    }
    return ReferenceCheckResponse(
        paper_id=paper_id,
        total=len(items),
        verified=counts["verified"],
        uncertain=counts["uncertain"],
        not_found=counts["not_found"],
        unavailable=counts["unavailable"],
        items=[ReferenceItem(**item) for item in items],
        cached=cached,
    )


@router.post("/references", response_model=ReferenceCheckResponse)
async def check_references(req: ReferenceCheckRequest) -> ReferenceCheckResponse:
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
            detail=f"Paper is not ready for reference checking (status: {paper['status']}).",
        )

    if not req.force:
        cached_result = (
            supabase.table(INTEGRITY_TABLE)
            .select("report_json")
            .eq("paper_id", req.paper_id)
            .limit(1)
            .execute()
        )
        if cached_result.data:
            return _build_response(
                req.paper_id, cached_result.data[0]["report_json"].get("items", []), cached=True
            )

    refs = extract_references(paper.get("structure_json") or {}, paper.get("raw_text") or "")
    items = await verify_all(refs, settings.crossref_mailto) if refs else []
    response = _build_response(req.paper_id, items, cached=False)
    supabase.table(INTEGRITY_TABLE).upsert(
        {"paper_id": req.paper_id, "report_json": response.model_dump(exclude={"cached"})},
        on_conflict="paper_id",
    ).execute()
    return response
