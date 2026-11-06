"""
Retraction alert: has a cited paper been retracted or corrected since?

Crossref records editorial notices (retractions, withdrawals, expressions of
concern, corrections) as "updates" to the original DOI, and since 2023 it
also carries the Retraction Watch database. One filtered search covers many
DOIs at once ("filter=updates:A,updates:B" returns every notice that updates
A or B), so a paper with 50 matched references needs only a few requests.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_CROSSREF_WORKS = "https://api.crossref.org/works"
_BATCH = 20  # DOIs per request; keeps the URL short
# Notice types, most serious first. Anything else Crossref sends ("addendum",
# "new_edition", ...) is not something a reader needs to be warned about.
SERIOUS = ("retraction", "withdrawal", "removal", "expression_of_concern")
MINOR = ("correction", "erratum", "corrigendum")
_KNOWN = SERIOUS + MINOR


def _normalize(doi: str) -> str:
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi.strip(), flags=re.IGNORECASE).lower()


def _notice_type(value: str) -> str:
    kind = value.strip().lower().replace(" ", "_").replace("-", "_")
    return {"expression_of_concern": "expression_of_concern", "partial_retraction": "retraction"}.get(kind, kind)


def _date(update: dict[str, Any]) -> str | None:
    parts = ((update.get("updated") or {}).get("date-parts") or [[None]])[0]
    if not parts or not parts[0]:
        return None
    return "-".join(f"{int(p):02d}" if i else str(int(p)) for i, p in enumerate(parts[:3]))


def _parse(items: list[dict[str, Any]], wanted: set[str]) -> dict[str, list[dict[str, Any]]]:
    found: dict[str, dict[tuple[str, str | None], dict[str, Any]]] = {}
    for item in items:
        notice_doi = item.get("DOI")
        for update in item.get("update-to") or []:
            target = _normalize(str(update.get("DOI") or ""))
            kind = _notice_type(str(update.get("type") or ""))
            if target not in wanted or kind not in _KNOWN:
                continue
            notice = {
                "type": kind,
                "label": str(update.get("label") or kind.replace("_", " ").capitalize()),
                "date": _date(update),
                "notice_doi": notice_doi,
                "source": "Retraction Watch" if update.get("source") == "retraction-watch" else "Crossref",
            }
            # Publisher and Retraction Watch often record the same notice twice.
            found.setdefault(target, {}).setdefault((kind, notice["date"]), notice)
    order = {kind: i for i, kind in enumerate(_KNOWN)}
    return {
        doi: sorted(notices.values(), key=lambda n: (order.get(n["type"], 99), n["date"] or ""))
        for doi, notices in found.items()
    }


async def find_notices(dois: list[str], mailto: str = "") -> tuple[dict[str, list[dict[str, Any]]], bool]:
    """Editorial notices for each DOI, and whether every lookup succeeded.

    DOIs with no notices are absent from the result. A failed batch is
    logged and reported through the flag, never raised: the reference check
    must still be shown when Crossref is busy.
    """
    wanted = sorted({_normalize(d) for d in dois if d and "," not in d})
    if not wanted:
        return {}, True
    headers = {"User-Agent": f"ReSense/1.0 (mailto:{mailto})"} if mailto else {}
    results: dict[str, list[dict[str, Any]]] = {}
    complete = True
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        for start in range(0, len(wanted), _BATCH):
            batch = wanted[start : start + _BATCH]
            params = {
                "filter": ",".join(f"updates:{doi}" for doi in batch),
                "select": "DOI,update-to",
                "rows": 200,
            }
            if mailto:
                params["mailto"] = mailto
            try:
                response = await client.get(_CROSSREF_WORKS, params=params)
                response.raise_for_status()
                items = response.json()["message"]["items"]
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                logger.warning("Retraction lookup failed for %d DOIs: %s", len(batch), exc)
                complete = False
                continue
            results.update(_parse(items, set(batch)))
    return results, complete


def is_serious(notices: list[dict[str, Any]] | None) -> bool:
    return any(n.get("type") in SERIOUS for n in notices or [])
