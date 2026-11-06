"""
Integrity report for a paper, saved per paper in integrity_reports:

- /integrity/references: is every reference a real, published work, and has
  any of them been retracted or corrected since (retraction alert)?
- /integrity/links: do the paper's links still work, and is its data or code
  shared or only "available on request" (reproducibility check)?
- /integrity/claims: does each cited paper's abstract support what the
  citing sentence says about it (citation claim check)?

The three results live side by side in one saved report, so each check
keeps the others' results when it saves its own.
"""

import asyncio
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response

from app.config import settings
from app.db.supabase_client import INTEGRITY_TABLE, PAPERS_TABLE, get_supabase
from app.models.schemas import (
    ClaimCheckResponse,
    ClaimItem,
    IntegrityRequest,
    LinkCheckResponse,
    LinkItem,
    ReferenceCheckRequest,
    ReferenceCheckResponse,
    ReferenceItem,
)
from app.auth import CurrentUser, current_user
from app.services import claims as claim_check
from app.services import links as link_check
from app.services.references import extract_reference_title, extract_references, verify_all
from app.services.retractions import find_notices, is_serious

logger = logging.getLogger(__name__)

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
    paper_id: str, report: dict | list, cached: bool, checked_at: str | None = None
) -> ReferenceCheckResponse:
    report = {"items": report} if isinstance(report, list) else report
    items = report.get("items", [])
    counts = {
        status: sum(item["status"] == status for item in items)
        for status in ("verified", "uncertain", "not_found", "unavailable")
    }
    serious = sum(is_serious(item.get("notices")) for item in items)
    corrected = sum(bool(item.get("notices")) and not is_serious(item.get("notices")) for item in items)
    return ReferenceCheckResponse(
        paper_id=paper_id,
        total=len(items),
        **counts,
        items=[ReferenceItem(**{**item, **_cited_parts(item["raw"])}) for item in items],
        cached=cached,
        checked_at=checked_at,
        retracted=serious,
        corrected=corrected,
        notices_checked=bool(report.get("notices_checked")),
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


def _ready(paper: dict, what: str) -> None:
    if paper["status"] != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Paper is not ready for {what} (status: {paper['status']}).",
        )


def _saved_row(supabase, paper_id: str) -> dict | None:
    result = (
        supabase.table(INTEGRITY_TABLE)
        .select("report_json, generated_at")
        .eq("paper_id", paper_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _saved_references(row: dict | None) -> dict | None:
    """The saved reference check, if one has been run (links or claims may exist alone)."""
    report = (row or {}).get("report_json") or {}
    return report if "items" in report else None


# One check at a time per paper, so two checks finishing together can't
# overwrite each other's part of the saved report.
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _save_part(supabase, paper_id: str, part: dict, references_checked_at: str | None = None) -> None:
    """Save one check's result into the paper's report, keeping the other checks."""
    row = _saved_row(supabase, paper_id) or {}
    report = {**(row.get("report_json") or {}), **part}
    supabase.table(INTEGRITY_TABLE).upsert(
        {
            "paper_id": paper_id,
            "report_json": report,
            "generated_at": references_checked_at or row.get("generated_at") or _now(),
        },
        on_conflict="paper_id",
    ).execute()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_REFERENCES_HEADING_RE = re.compile(
    r"^[ \t]*(?:\d{1,2}\.?|[IVX]{1,4}\.)?[ \t]*(references|bibliography|literature cited|works cited)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)


def _references_start(raw_text: str) -> int | None:
    """Where the reference list begins; the body is everything before it."""
    matches = list(_REFERENCES_HEADING_RE.finditer(raw_text))
    return matches[-1].start() if matches else None


# --------------------------------------------------------------- references


@router.get("/references/{paper_id}", response_model=ReferenceCheckResponse)
async def saved_reference_check(paper_id: str, user: CurrentUser = Depends(current_user)):
    """The last saved check, without starting a new one. 204 if it was never run."""
    supabase = get_supabase()
    _owned_paper(supabase, paper_id, user, columns="id")
    row = _saved_row(supabase, paper_id)
    report = _saved_references(row)
    if report is None:
        return Response(status_code=204)
    return _build_response(paper_id, report, cached=True, checked_at=row.get("generated_at"))


async def _with_notices(items: list[dict]) -> tuple[list[dict], bool]:
    """Attach retraction and correction notices to every matched reference."""
    dois = [item["matched_doi"] for item in items if item.get("matched_doi") and item["status"] in ("verified", "uncertain")]
    notices, complete = await find_notices(dois, settings.crossref_mailto)
    updated = []
    for item in items:
        doi = (item.get("matched_doi") or "").lower()
        keep = item["status"] in ("verified", "uncertain")
        updated.append({**item, "notices": notices.get(doi, []) if keep else []})
    return updated, complete


@router.post("/references", response_model=ReferenceCheckResponse)
async def check_references(
    req: ReferenceCheckRequest, user: CurrentUser = Depends(current_user)
) -> ReferenceCheckResponse:
    supabase = get_supabase()
    paper = _owned_paper(supabase, req.paper_id, user)
    _ready(paper, "reference checking")

    async with _locks[req.paper_id]:
        if not req.force:
            row = _saved_row(supabase, req.paper_id)
            saved = _saved_references(row)
            if saved is not None:
                cached_items = saved.get("items", [])
                retry = [item for item in cached_items if item.get("status") == "unavailable"]
                if not retry and saved.get("notices_checked"):
                    return _build_response(req.paper_id, saved, cached=True, checked_at=row.get("generated_at"))
                items = cached_items
                if retry:
                    # A provider was down or rate-limited last time: re-check only those
                    # references and keep every settled result as it was.
                    rechecked = await verify_all(
                        [item["raw"] for item in retry],
                        settings.crossref_mailto,
                        openalex_api_key=settings.openalex_api_key,
                    )
                    by_index = {old["index"]: {**new, "index": old["index"]} for old, new in zip(retry, rechecked)}
                    items = [by_index.get(item["index"], item) for item in cached_items]
                return await _save_references(supabase, req.paper_id, items)

        refs = extract_references(paper.get("structure_json") or {}, paper.get("raw_text") or "")
        items = (
            await verify_all(refs, settings.crossref_mailto, openalex_api_key=settings.openalex_api_key)
            if refs
            else []
        )
        return await _save_references(supabase, req.paper_id, items)


async def _save_references(supabase, paper_id: str, items: list[dict]) -> ReferenceCheckResponse:
    items, notices_checked = await _with_notices(items)
    checked_at = _now()
    report = {"items": items, "notices_checked": notices_checked}
    response = _build_response(paper_id, report, cached=False, checked_at=checked_at)
    # Saved as returned (with display fields), so a saved report reads back the same.
    saved_items = [item.model_dump() for item in response.items]
    _save_part(supabase, paper_id, {"items": saved_items, "notices_checked": notices_checked}, checked_at)
    return response


# --------------------------------------------------------------- links


def _links_response(paper_id: str, part: dict, cached: bool) -> LinkCheckResponse:
    found = part.get("links", [])
    return LinkCheckResponse(
        paper_id=paper_id,
        total=len(found),
        working=sum(link["status"] == "working" for link in found),
        broken=sum(link["status"] == "broken" for link in found),
        unconfirmed=sum(link["status"] in ("unconfirmed", "skipped") for link in found),
        links=[LinkItem(**link) for link in found],
        statements=part.get("statements", []),
        checked_at=part.get("checked_at"),
        cached=cached,
    )


@router.get("/links/{paper_id}", response_model=LinkCheckResponse)
async def saved_link_check(paper_id: str, user: CurrentUser = Depends(current_user)):
    supabase = get_supabase()
    _owned_paper(supabase, paper_id, user, columns="id")
    part = ((_saved_row(supabase, paper_id) or {}).get("report_json") or {}).get("links_check")
    if not part:
        return Response(status_code=204)
    return _links_response(paper_id, part, cached=True)


@router.post("/links", response_model=LinkCheckResponse)
async def check_links(req: IntegrityRequest, user: CurrentUser = Depends(current_user)) -> LinkCheckResponse:
    supabase = get_supabase()
    paper = _owned_paper(supabase, req.paper_id, user)
    _ready(paper, "link checking")
    async with _locks[req.paper_id]:
        if not req.force:
            part = ((_saved_row(supabase, req.paper_id) or {}).get("report_json") or {}).get("links_check")
            if part:
                return _links_response(req.paper_id, part, cached=True)
        raw_text = paper.get("raw_text") or ""
        refs_start = _references_start(raw_text)
        found = link_check.extract_links(raw_text, refs_start)
        checked = await link_check.check_links(found) if found else []
        # Broken first, then the ones to confirm, then the working ones.
        order = {"broken": 0, "unconfirmed": 1, "skipped": 2, "working": 3}
        checked.sort(key=lambda link: (order[link["status"]], link["where"] != "body"))
        part = {
            "links": checked,
            "statements": link_check.availability_statements(raw_text[:refs_start] if refs_start else raw_text),
            "checked_at": _now(),
        }
        _save_part(supabase, req.paper_id, {"links_check": part})
        return _links_response(req.paper_id, part, cached=False)


# --------------------------------------------------------------- claims


def _claims_response(paper_id: str, part: dict, cached: bool) -> ClaimCheckResponse:
    found = part.get("claims", [])
    counts = {
        verdict: sum(claim["verdict"] == verdict for claim in found)
        for verdict in ("supported", "partial", "not_supported", "cannot_tell", "unchecked")
    }
    return ClaimCheckResponse(
        paper_id=paper_id,
        total=len(found),
        **counts,
        claims=[ClaimItem(**claim) for claim in found],
        citing_sentences=part.get("citing_sentences", 0),
        without_abstract=part.get("without_abstract", 0),
        checked_at=part.get("checked_at"),
        cached=cached,
    )


@router.get("/claims/{paper_id}", response_model=ClaimCheckResponse)
async def saved_claim_check(paper_id: str, user: CurrentUser = Depends(current_user)):
    supabase = get_supabase()
    _owned_paper(supabase, paper_id, user, columns="id")
    part = ((_saved_row(supabase, paper_id) or {}).get("report_json") or {}).get("claims_check")
    if not part:
        return Response(status_code=204)
    return _claims_response(paper_id, part, cached=True)


@router.post("/claims", response_model=ClaimCheckResponse)
async def check_claims(req: IntegrityRequest, user: CurrentUser = Depends(current_user)) -> ClaimCheckResponse:
    supabase = get_supabase()
    paper = _owned_paper(supabase, req.paper_id, user)
    _ready(paper, "claim checking")
    async with _locks[req.paper_id]:
        row = _saved_row(supabase, req.paper_id)
        if not req.force:
            part = ((row or {}).get("report_json") or {}).get("claims_check")
            if part and not any(claim["verdict"] == "unchecked" for claim in part.get("claims", [])):
                return _claims_response(req.paper_id, part, cached=True)
        saved = _saved_references(row)
        if saved is None:
            raise HTTPException(status_code=409, detail="Check the references first. The claim check uses their results.")

        items = saved.get("items", [])
        raw_text = paper.get("raw_text") or ""
        refs_start = _references_start(raw_text)
        citations = claim_check.find_citations(raw_text[:refs_start] if refs_start else raw_text, items)
        matched = {item["index"]: item for item in items if item["status"] in ("verified", "uncertain")}
        cited = {ref for citation in citations for ref in citation["refs"] if ref in matched}
        # Fetch abstracts only for references a claim could use, best claims first.
        candidates = claim_check.select_claims(citations, cited, limit=claim_check.MAX_CLAIMS * 2)
        wanted = list(dict.fromkeys(claim["ref"] for claim in candidates))
        abstracts = await claim_check.fetch_abstracts(
            [matched[ref] for ref in wanted], settings.crossref_mailto, settings.openalex_api_key
        )
        chosen = claim_check.select_claims(citations, set(abstracts))
        for claim in chosen:
            claim.update(
                source_title=abstracts[claim["ref"]]["title"] or matched[claim["ref"]].get("matched_title"),
                abstract=abstracts[claim["ref"]]["abstract"],
                abstract_source=abstracts[claim["ref"]]["source"],
                cited_title=matched[claim["ref"]].get("cited_title") or _cited_parts(matched[claim["ref"]]["raw"])["cited_title"],
            )
        judged = await claim_check.judge(chosen) if chosen else []
        if chosen and all(claim["verdict"] == "unchecked" for claim in judged):
            raise HTTPException(
                status_code=503,
                detail="The AI service didn't answer, so no claims were checked. Try again in a minute.",
            )
        order = {"not_supported": 0, "partial": 1, "cannot_tell": 2, "unchecked": 3, "supported": 4}
        judged.sort(key=lambda claim: (order[claim["verdict"]], claim["ref"]))
        part = {
            "claims": [
                {key: claim.get(key) for key in ("ref", "sentence", "verdict", "reason", "cited_title", "source_title", "abstract_source")}
                for claim in judged
            ],
            "citing_sentences": len(citations),
            "without_abstract": len(set(wanted) - set(abstracts)),
            "checked_at": _now(),
        }
        _save_part(supabase, req.paper_id, {"claims_check": part})
        return _claims_response(req.paper_id, part, cached=False)
