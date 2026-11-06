"""
Citation Claim Check: does a cited paper actually say what the sentence
citing it claims?

1. Find the sentences in the paper's body that cite a reference, for
   numbered ("[12]", "[3-5]") and author-year ("He et al., 2016") styles.
2. Keep the clearest claims: one or two references cited, a real sentence,
   and preferably one that states a finding.
3. Fetch the cited paper's abstract from OpenAlex, arXiv or Crossref.
4. A free AI model compares each claim with the abstract, several claims
   per request, and answers supported / partly / doesn't match / can't tell.

Only the abstract is compared, so "can't tell" is a common, honest answer:
a detail can be in the paper without being in its abstract.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from typing import Any

import httpx

from app.services.llm import LLMRequestError, call_openrouter
from app.services.references import extract_arxiv_id

logger = logging.getLogger(__name__)

MAX_CLAIMS = 30
_BATCH = 6
_ABSTRACT_CHARS = 1500
_OPENALEX = "https://api.openalex.org/works"
_ARXIV = "https://export.arxiv.org/api/query"
_CROSSREF = "https://api.crossref.org/works/"

VERDICTS = ("supported", "partial", "not_supported", "cannot_tell")

# ------------------------------------------------------------ citations

_ABBREVIATIONS = re.compile(r"\b(et al|e\.g|i\.e|cf|Fig|Figs|Eq|Eqs|Sec|Tab|vs|approx|resp|No|Vol|pp|Dr|Mr|Ms|Prof)\.", re.IGNORECASE)
# A new sentence, or a numbered heading run into the text ("... Section 5.2. 4.2 SQuAD").
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[\"“]|\d{1,2}(?:\.\d{1,2})*\s+[A-Z][A-Za-z])")
_NUMBERED = re.compile(r"\[(\s*\d{1,3}(?:\s*[-–—,;]\s*\d{1,3})*\s*)\]")
_NAME = r"[A-Z][A-Za-z'’\-]+(?:\s+(?:van|von|de|der|da|di|le|la)\s+[A-Z][A-Za-z'’\-]+)?"
_AUTHOR_YEAR = re.compile(
    rf"({_NAME})(?:\s+et\s+al\.?|\s+(?:and|&)\s+{_NAME})?,?\s*\(?((?:19|20)\d{{2}})[a-z]?\)?"
)


def _sentences(text: str) -> list[str]:
    flat = re.sub(r"-\n(?=[a-z])", "", text)
    flat = re.sub(r"\s+", " ", flat)
    protected = _ABBREVIATIONS.sub(lambda m: m.group(0).replace(".", "․"), flat)
    return [s.replace("․", ".").strip() for s in _SPLIT.split(protected) if s.strip()]


def _expand(numbers: str) -> list[int]:
    found: list[int] = []
    for part in re.split(r"[,;]", numbers):
        bounds = [int(n) for n in re.findall(r"\d+", part)]
        if len(bounds) == 2 and 0 < bounds[1] - bounds[0] <= 10:
            found.extend(range(bounds[0], bounds[1] + 1))
        else:
            found.extend(bounds)
    return found


def _marker_number(raw: str) -> int | None:
    match = re.match(r"\s*(?:\[(\d{1,3})\]|(\d{1,3})[.)]\s)", raw)
    return int(match.group(1) or match.group(2)) if match else None


def _first_author_index(references: list[dict[str, Any]]) -> dict[tuple[str, str], list[int]]:
    """(surname, year) -> references whose author list starts with that surname."""
    index: dict[tuple[str, str], list[int]] = {}
    for item in references:
        raw = re.sub(r"^\s*(?:\[\d+\]|\d+[.)])\s*", "", item["raw"])
        year = re.search(r"\b((?:19|20)\d{2})[a-z]?\b", raw)
        if not year:
            continue
        head = raw[: max(year.start(), 40)][:120]
        names = re.findall(r"[A-Z][A-Za-z'’\-]{1,}", head)
        # "He, K., Zhang, X." and "K. He, X. Zhang" both put the first surname early.
        for name in names[:3]:
            index.setdefault((name.lower(), year.group(1)), []).append(item["index"])
    return index


def _not_prose(sentence: str) -> bool:
    """Table rows, contents pages and other text that isn't a sentence."""
    plain = _NUMBERED.sub("", sentence)
    digits = sum(ch.isdigit() for ch in plain)
    letters = sum(ch.isalpha() for ch in plain)
    return ". . ." in sentence or letters < 25 or digits > 0.12 * (letters + digits)


def find_citations(body_text: str, references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each citing sentence with the reference indexes it cites."""
    by_number = {n: item["index"] for item in references if (n := _marker_number(item["raw"])) is not None}
    numbered = bool(by_number) and len(by_number) >= len(references) // 2
    by_author = {} if numbered else _first_author_index(references)
    known = {item["index"] for item in references}
    found: list[dict[str, Any]] = []
    for sentence in _sentences(body_text):
        if not 40 <= len(sentence) <= 450 or _not_prose(sentence):
            continue
        refs: list[int] = []
        if numbered:
            for match in _NUMBERED.finditer(sentence):
                refs.extend(by_number[n] for n in _expand(match.group(1)) if n in by_number)
        else:
            for match in _AUTHOR_YEAR.finditer(sentence):
                candidates = by_author.get((match.group(1).lower(), match.group(2)), [])
                if len(candidates) == 1:  # ambiguous "Smith 2019a/b" is skipped
                    refs.append(candidates[0])
        refs = [r for r in dict.fromkeys(refs) if r in known]
        if refs:
            found.append({"sentence": sentence, "refs": refs})
    return found


_FINDING_RE = re.compile(
    r"\b(show|shows|showed|shown|found|find|finds|demonstrat\w*|achiev\w*|outperform\w*|improv\w*|reduc\w*|"
    r"increas\w*|report\w*|prove\w*|propos\w*|introduc\w*|reach\w*|obtain\w*|state-of-the-art|"
    r"better|worse|faster|accura\w*|error)\b|\d",
    re.IGNORECASE,
)


def select_claims(citations: list[dict[str, Any]], usable: set[int], limit: int = MAX_CLAIMS) -> list[dict[str, Any]]:
    """The clearest claim per cited reference first, then a second one, up to the limit."""
    per_ref: dict[int, list[tuple[int, str]]] = {}
    for citation in citations:
        if len(citation["refs"]) > 2:
            continue  # "[3, 5, 8, 9]" is background, not a specific claim
        plain = _AUTHOR_YEAR.sub("", _NUMBERED.sub("", citation["sentence"]))
        score = (2 if _FINDING_RE.search(plain) else 0) + (1 if len(citation["refs"]) == 1 else 0)
        for ref in citation["refs"]:
            if ref in usable:
                per_ref.setdefault(ref, []).append((score, citation["sentence"]))
    rounds: list[list[dict[str, Any]]] = [[], []]
    for ref, options in per_ref.items():
        best: dict[str, int] = {}
        for score, sentence in options:
            best[sentence] = max(score, best.get(sentence, 0))
        ranked = sorted(best.items(), key=lambda pair: -pair[1])
        for round_no, (sentence, score) in enumerate(ranked[:2]):
            rounds[round_no].append({"ref": ref, "sentence": sentence, "score": score})
    chosen = sorted(rounds[0], key=lambda c: (-c["score"], c["ref"])) + sorted(rounds[1], key=lambda c: (-c["score"], c["ref"]))
    return chosen[:limit]


# ------------------------------------------------------------ abstracts


def _from_inverted_index(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    words: dict[int, str] = {}
    for word, positions in index.items():
        for position in positions:
            words[position] = word
    return " ".join(words[i] for i in sorted(words))


def _clean_abstract(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    text = re.sub(r"^\s*abstract[:.\s]+", "", re.sub(r"\s+", " ", text).strip(), flags=re.IGNORECASE)
    return text[:_ABSTRACT_CHARS]


def _arxiv_id(item: dict[str, Any]) -> str | None:
    doi = (item.get("matched_doi") or "").lower()
    if doi.startswith("10.48550/arxiv."):
        return doi.removeprefix("10.48550/arxiv.")
    return extract_arxiv_id(item.get("raw") or "")


async def fetch_abstracts(
    items: list[dict[str, Any]], mailto: str = "", openalex_api_key: str = ""
) -> dict[int, dict[str, str]]:
    """index -> {"title", "abstract", "source"} for each reference we could find one for."""
    found: dict[int, dict[str, str]] = {}
    headers = {"User-Agent": f"ReSense/1.0 (mailto:{mailto})"} if mailto else {}
    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        by_doi = {item["matched_doi"].lower(): item for item in items if item.get("matched_doi")}
        dois = list(by_doi)
        for start in range(0, len(dois), 40):
            batch = dois[start : start + 40]
            params: dict[str, Any] = {
                "filter": "doi:" + "|".join(batch),
                "select": "doi,title,abstract_inverted_index",
                "per_page": 50,
            }
            if openalex_api_key:
                params["api_key"] = openalex_api_key
            elif mailto:
                params["mailto"] = mailto
            try:
                response = await client.get(_OPENALEX, params=params)
                response.raise_for_status()
                for work in response.json().get("results", []):
                    doi = re.sub(r"^https?://doi\.org/", "", str(work.get("doi") or "")).lower()
                    abstract = _clean_abstract(_from_inverted_index(work.get("abstract_inverted_index")))
                    if doi in by_doi and len(abstract) > 80:
                        found[by_doi[doi]["index"]] = {"title": work.get("title") or "", "abstract": abstract, "source": "OpenAlex"}
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                logger.warning("OpenAlex abstract lookup failed: %s", exc)

        missing = [item for item in items if item["index"] not in found]
        arxiv = {aid: item for item in missing if (aid := _arxiv_id(item))}
        ids = list(arxiv)
        for start in range(0, len(ids), 20):
            batch = ids[start : start + 20]
            try:
                response = await client.get(_ARXIV, params={"id_list": ",".join(batch), "max_results": len(batch)})
                response.raise_for_status()
                for entry in re.findall(r"<entry>(.*?)</entry>", response.text, re.DOTALL):
                    entry_id = re.search(r"<id>\s*https?://arxiv\.org/abs/([^<\s]+?)(?:v\d+)?\s*</id>", entry)
                    summary = re.search(r"<summary>(.*?)</summary>", entry, re.DOTALL)
                    title = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
                    if not entry_id or not summary:
                        continue
                    key = next((aid for aid in batch if aid.split("v")[0] == entry_id.group(1)), None)
                    if key:
                        found[arxiv[key]["index"]] = {
                            "title": re.sub(r"\s+", " ", title.group(1)).strip() if title else "",
                            "abstract": _clean_abstract(summary.group(1)),
                            "source": "arXiv",
                        }
            except httpx.HTTPError as exc:
                logger.warning("arXiv abstract lookup failed: %s", exc)

        # Crossref holds publisher abstracts for some journals; ask one by one, briefly.
        missing = [item for item in items if item["index"] not in found and item.get("matched_doi")][:15]

        async def crossref(item: dict[str, Any]) -> None:
            try:
                response = await client.get(_CROSSREF + item["matched_doi"], params={"mailto": mailto} if mailto else None)
                if response.status_code != 200:
                    return
                message = response.json().get("message", {})
                abstract = _clean_abstract(message.get("abstract") or "")
                if len(abstract) > 80:
                    found[item["index"]] = {"title": (message.get("title") or [""])[0], "abstract": abstract, "source": "Crossref"}
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("Crossref abstract lookup failed: %s", exc)

        await asyncio.gather(*(crossref(item) for item in missing))
    return found


# ------------------------------------------------------------ judging

_SYSTEM = """You check whether research papers cite their sources accurately.
For each numbered pair you get a CLAIM (a sentence from a paper, citing a source) and the ABSTRACT of the cited source.
Decide whether the abstract supports what the claim attributes to that source.

Verdicts:
- "supported": the abstract clearly backs the claim's statement about this source.
- "partial": the abstract backs part of it, or backs it in weaker or different terms (for example a different number or scope).
- "not_supported": the abstract is about something else, or contradicts what the claim says this source shows.
- "cannot_tell": the claim is about a detail an abstract would not normally state (a setting, a dataset detail, a definition), or the abstract is too short to judge.

Rules:
- A sentence may cite several sources; judge only the part that plausibly comes from this one.
- If the claim only says the source exists or proposed a method, and the abstract describes that method, it is "supported".
- Do not use outside knowledge about the papers. Judge from the abstract alone.
- Be fair: choose "not_supported" only when the abstract contradicts the claim, or the source is clearly about a different subject from what the claim attributes to it. If the abstract is on the same subject but simply doesn't mention the specific point, choose "cannot_tell".

Reply with only a JSON array, one object per pair, in order:
[{"id": 1, "verdict": "supported", "reason": "one short plain sentence"}]"""


def _prompt(batch: list[dict[str, Any]]) -> str:
    parts = []
    for number, claim in enumerate(batch, 1):
        parts.append(
            f"PAIR {number}\nCLAIM (citing reference [{claim['ref']}]): {claim['sentence']}\n"
            f"SOURCE TITLE: {claim['source_title']}\nABSTRACT: {claim['abstract']}"
        )
    return "\n\n".join(parts)


def _parse_verdicts(text: str, size: int) -> dict[int, dict[str, str]]:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON array in the reply")
    rows = json.loads(match.group(0))
    parsed: dict[int, dict[str, str]] = {}
    for position, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        number = int(row.get("id", position))
        verdict = str(row.get("verdict", "")).strip().lower().replace(" ", "_").replace("-", "_")
        verdict = {"partly": "partial", "partially_supported": "partial", "unsupported": "not_supported",
                   "unclear": "cannot_tell", "can't_tell": "cannot_tell"}.get(verdict, verdict)
        if 1 <= number <= size and verdict in VERDICTS:
            parsed[number] = {"verdict": verdict, "reason": str(row.get("reason", "")).strip()[:300]}
    return parsed


async def judge(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add "verdict" and "reason" to each claim; "unchecked" where the AI couldn't answer."""
    batches = [claims[i : i + _BATCH] for i in range(0, len(claims), _BATCH)]

    async def run(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for attempt in range(2):
            try:
                reply = await call_openrouter(_SYSTEM, _prompt(batch), max_tokens=1200, temperature=0.1, timeout=45.0)
                verdicts = _parse_verdicts(reply, len(batch))
                if verdicts:
                    break
            except (LLMRequestError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("Claim check batch failed (attempt %d): %s", attempt + 1, exc)
                verdicts = {}
        return [
            {**claim, **verdicts.get(n, {"verdict": "unchecked", "reason": ""})}
            for n, claim in enumerate(batch, 1)
        ]

    # Two requests at a time: quicker than one by one, and well inside the
    # free tiers' requests-per-minute limits.
    semaphore = asyncio.Semaphore(2)

    async def limited(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        async with semaphore:
            return await run(batch)

    done = await asyncio.gather(*(limited(batch) for batch in batches))
    return [claim for batch in done for claim in batch]
