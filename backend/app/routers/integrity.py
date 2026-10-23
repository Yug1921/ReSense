"""POST /integrity/references — deterministic Crossref reference checking."""

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response

from app.config import settings
from app.db.supabase_client import INTEGRITY_TABLE, PAPERS_TABLE, get_supabase
from app.models.schemas import (
    ReferenceCheckRequest,
    ReferenceCheckResponse,
    ReferenceItem,
)
from app.auth import CurrentUser, current_user
from app.services.references import extract_reference_title, extract_references, verify_all

router = APIRouter(prefix="/integrity", tags=["integrity"])


def _cited_parts(raw: str) -> dict:
    """Split a citation into title, authors and venue for display (best effort)."""
    cleaned = re.sub(r"^\s*(?:\[\d+\]|\(\d+\)|\d+[.)])\s*", "", raw).strip()
    cleaned = re.sub(r"\s+([,.])", r"\1", cleaned)
    title = extract_reference_title(raw).strip(" .,:;")
    title = re.sub(r"[.,]\s*(?:19|20)\d{2}[a-z]?$", "", title).strip(" .,:;")
    bare_arxiv = re.search(r"[.,]?\s*(\d{4}\.\d{4,5}(?:v\d+)?)$", title)
    if bare_arxiv:
        title = title[: bare_arxiv.start()].strip(" .,:;")
    position = cleaned.lower().find(title.lower()) if title else -1
    if not title or position < 0:
        return {"cited_title": None, "cited_authors": None, "cited_venue": None}
    # Author-year styles put the year after the names: "A. Author. 2018a."
    authors = re.sub(r"[.,]?\s*\(?(?:19|20)\d{2}[a-z]?\)?$", "", cleaned[:position].strip(" .,:;"))
    authors = authors.strip(" .,:;") or None
    rest = cleaned[position + len(title):].strip(" .,:;")
    rest = re.sub(r"^In\s+", "", rest)
    rest = re.sub(r"^.*?\beditors?\s*,\s*", "", rest)
    # Volume, issue and pages ("33", "5(2):157-166", "pages 1532- 1543") are noise in a one-line venue.
    rest = re.sub(r"(?:,\s*)?(?:volume|vol\.)\s*\d+", "", rest)
    rest = re.sub(r"(?:,\s*)?(?:pages?|pp?\.)\s*\d+(?:\s*[\u2013\u2014-]+\s*\d+)?", "", rest)
    # Only a year at the end is dropped; "Proceedings of the 2016 Conference" keeps its own.
    rest = re.sub(r"[\s,]*\b(?:19|20)\d{2}[a-z]?$", "", rest.strip(" .,:;")).strip(" .,:;")
    rest = re.sub(r"[\s,]*(?<![.:/\w])\d+(?:\([^)]*\))?(?::\s*[\d\u2013\u2014-]+)?$", "", rest).strip(" .,:;'\u2019")
    if bare_arxiv:
        rest = re.sub(re.escape(bare_arxiv.group(1)), "", rest).strip(" .,:;")
        rest = rest or f"arXiv:{bare_arxiv.group(1)}"
    return {"cited_title": title, "cited_authors": authors, "cited_venue": rest[:160] or None}


def _build_response(
    paper_id: str, items: list[dict], cached: bool, checked_at: str | None = None
) -> ReferenceCheckResponse:
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
        items=[ReferenceItem(**{**item, **_cited_parts(item["raw"])}) for item in items],
        cached=cached,
        checked_at=checked_at,
    )


def _owned_paper(supabase, paper_id: str, user: CurrentUser, columns: str = "*") -> dict:
    result = (
        supabase.table(PAPERS_TABLE)
        .select(columns)
        .eq("id", paper_id)
        .eq("user_id", user.id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="No paper found for this paper_id.")
    return result.data[0]


def _saved_report(supabase, paper_id: str) -> dict | None:
    result = (
        supabase.table(INTEGRITY_TABLE)
        .select("report_json, generated_at")
        .eq("paper_id", paper_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


@router.get("/references/{paper_id}", response_model=ReferenceCheckResponse)
async def saved_reference_check(paper_id: str, user: CurrentUser = Depends(current_user)):
    """The last saved check, without starting a new one. 204 if it was never run."""
    supabase = get_supabase()
    _owned_paper(supabase, paper_id, user, columns="id")
    saved = _saved_report(supabase, paper_id)
    if not saved:
        return Response(status_code=204)
    return _build_response(
        paper_id, saved["report_json"].get("items", []), cached=True, checked_at=saved.get("generated_at")
    )


@router.post("/references", response_model=ReferenceCheckResponse)
async def check_references(
    req: ReferenceCheckRequest, user: CurrentUser = Depends(current_user)
) -> ReferenceCheckResponse:
    supabase = get_supabase()
    paper = _owned_paper(supabase, req.paper_id, user)
    if paper["status"] != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Paper is not ready for reference checking (status: {paper['status']}).",
        )

    if not req.force:
        saved = _saved_report(supabase, req.paper_id)
        if saved:
            cached_items = saved["report_json"].get("items", [])
            retry = [item for item in cached_items if item.get("status") == "unavailable"]
            if not retry:
                return _build_response(req.paper_id, cached_items, cached=True, checked_at=saved.get("generated_at"))
            # A provider was down or rate-limited last time: re-check only those
            # references and keep every settled result as it was.
            rechecked = await verify_all(
                [item["raw"] for item in retry],
                settings.crossref_mailto,
                openalex_api_key=settings.openalex_api_key,
            )
            by_index = {old["index"]: {**new, "index": old["index"]} for old, new in zip(retry, rechecked)}
            items = [by_index.get(item["index"], item) for item in cached_items]
            return _save_report(supabase, req.paper_id, items)

    refs = extract_references(paper.get("structure_json") or {}, paper.get("raw_text") or "")
    items = (
        await verify_all(refs, settings.crossref_mailto, openalex_api_key=settings.openalex_api_key)
        if refs
        else []
    )
    return _save_report(supabase, req.paper_id, items)


def _save_report(supabase, paper_id: str, items: list[dict]) -> ReferenceCheckResponse:
    checked_at = datetime.now(timezone.utc).isoformat()
    response = _build_response(paper_id, items, cached=False, checked_at=checked_at)
    supabase.table(INTEGRITY_TABLE).upsert(
        {
            "paper_id": paper_id,
            "report_json": response.model_dump(exclude={"cached", "checked_at"}),
            "generated_at": checked_at,
        },
        on_conflict="paper_id",
    ).execute()
    return response
