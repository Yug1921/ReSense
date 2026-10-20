"""Reference extraction and Crossref-based integrity verification."""

import asyncio
import html
import logging
import re
import time
import unicodedata
import weakref
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from dataclasses import dataclass
from typing import Any

import httpx
from bs4 import BeautifulSoup


_DOI_RE = re.compile(r"""10\.\d{4,9}/[^\s"<>]+""", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}(?=[a-z]?\b)")
_REFERENCE_MARKER_RE = re.compile(r"(?m)^\s*\[(\d+)\]\s*")
_NUMBERED_REFERENCE_RE = re.compile(r"(?m)^\s*(\d+)[.)]\s+")
_PLAIN_NUMBERED_REFERENCE_RE = re.compile(r"(?m)^\s*(\d{1,3})\s+(?=[A-Z][A-Za-z])")
_AUTHOR_YEAR_MARKER_RE = re.compile(r"(?m)\b(?:19|20)\d{2}[a-z]?\.\s")
_AUTHOR_YEAR_LINE_RE = re.compile(
    r"^(?:[A-Z][A-Za-z'’-]+(?:\s+[A-Z](?:[A-Za-z'’-]+)?\.?)+|"
    r"[A-Z][A-Za-z'’-]+,\s*[A-Z]\.|[A-Z]\.\s+[A-Z][A-Za-z'’-]+)"
)
_AUTHOR_YEAR_NON_AUTHOR_PREFIX_RE = re.compile(
    r"^(?:in|image|language|long|proceedings|association)\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_ISBN_RE = re.compile(
    r"(?:ISBN(?:-\d+)?\s*[:#]?\s*)?"
    r"([0-9Xx][0-9Xx\s-]{8,16}[0-9Xx])",
    re.IGNORECASE,
)
_TRAILING_DOI_PUNCTUATION = ".,;:!?)]}"
_CROSSREF_URL = "https://api.crossref.org"
_ARXIV_API_URL = "https://export.arxiv.org/api/query"
_OPENALEX_URL = "https://api.openalex.org/works"
_JMLR_URL = "https://www.jmlr.org"
_JMLR_VOLUME_URL = f"{_JMLR_URL}/papers/v{{volume}}/"
_NEURIPS_URL = "https://proceedings.neurips.cc"
_NEURIPS_YEAR_URL = f"{_NEURIPS_URL}/paper/{{year}}"
_MAX_ATTEMPTS = 3
_MAX_RETRY_DELAY = 30.0
# After this many requests to one host fail outright (all retries spent on
# network errors), stop calling that host for the rest of the run.
_HOST_FAILURE_LIMIT = 3
logger = logging.getLogger(__name__)


class _HostPacer:
    """Caps concurrency and request rate for one host, shared by all workers.

    A 429 from any worker pauses every worker for that host, so retries do not
    keep hammering a provider that has already asked us to slow down.
    """

    def __init__(self, concurrency: int, min_interval: float) -> None:
        self._semaphore = asyncio.Semaphore(concurrency)
        self._lock = asyncio.Lock()
        self._min_interval = min_interval
        self._next_start = 0.0
        self._cooldown_until = 0.0
        self._failures = 0
        self.unavailable_reason: str | None = None

    async def __aenter__(self) -> "_HostPacer":
        await self._semaphore.acquire()
        try:
            async with self._lock:
                now = time.monotonic()
                start = max(now, self._next_start, self._cooldown_until)
                self._next_start = start + self._min_interval
            if start > now:
                await asyncio.sleep(start - now)
        except BaseException:
            self._semaphore.release()
            raise
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        self._semaphore.release()

    def cool_down(self, seconds: float) -> None:
        self._cooldown_until = max(self._cooldown_until, time.monotonic() + seconds)

    def give_up(self, reason: str) -> None:
        if self.unavailable_reason is None:
            logger.warning("Skipping %s for the rest of this run", reason)
        self.unavailable_reason = reason

    def record_success(self) -> None:
        self._failures = 0

    def record_failure(self, host: str) -> None:
        self._failures += 1
        if self._failures >= _HOST_FAILURE_LIMIT:
            self.give_up(f"{host}: unreachable after {self._failures} failed requests")


# Pacers live per HTTP client so each report run (and each test event loop)
# gets fresh asyncio primitives. Clients without pacers are not throttled.
_CLIENT_PACERS: "weakref.WeakKeyDictionary[httpx.AsyncClient, dict[str, _HostPacer]]" = (
    weakref.WeakKeyDictionary()
)


def _provider_pacers(polite: bool) -> dict[str, _HostPacer]:
    # Crossref (from Dec 2025): query requests are limited to 1/s with 1
    # concurrent request on the public pool, 3/s with 3 concurrent on the
    # polite pool (requests carrying a mailto). arXiv asks for at most one
    # API request every 3 seconds. JMLR/NeurIPS are plain websites.
    return {
        "api.crossref.org": _HostPacer(3, 0.34) if polite else _HostPacer(1, 1.0),
        "api.openalex.org": _HostPacer(2, 0.2),
        "export.arxiv.org": _HostPacer(1, 3.0),
        "www.jmlr.org": _HostPacer(1, 1.0),
        "proceedings.neurips.cc": _HostPacer(1, 1.0),
    }


class _NoPacer:
    unavailable_reason = None

    async def __aenter__(self) -> "_NoPacer":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None

    def cool_down(self, seconds: float) -> None:
        return None

    def give_up(self, reason: str) -> None:
        return None

    def record_success(self) -> None:
        return None

    def record_failure(self, host: str) -> None:
        return None


def _pacer_for(client: httpx.AsyncClient, url: str) -> "_HostPacer | _NoPacer":
    pacers = _CLIENT_PACERS.get(client)
    if not pacers:
        return _NoPacer()
    return pacers.get(httpx.URL(url).host) or _NoPacer()


def _retry_after(response: httpx.Response | None) -> float | None:
    retry_after = response.headers.get("Retry-After") if response is not None else None
    try:
        return max(0.0, float(retry_after)) if retry_after else None
    except ValueError:
        return None


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    retry_after = _retry_after(response)
    delay = retry_after if retry_after is not None else 2**attempt
    return min(delay, _MAX_RETRY_DELAY)


@dataclass
class ReferenceMetadata:
    title: str
    authors: list[str]
    author_surnames: list[str]
    first_author: str | None
    year: int | None
    doi: str | None
    arxiv_id: str | None
    venue: str | None
    publisher: str | None
    isbn: str | None
    document_type: str
    volume: int | None = None
    issue: int | None = None
    page_start: int | None = None
    page_end: int | None = None


def _section_text(section: Any) -> str:
    if isinstance(section, str):
        return section
    if isinstance(section, list):
        return "\n".join(str(item) for item in section)
    return ""


def _split_references(text: str, marker_pattern: re.Pattern[str]) -> list[str]:
    matches = list(marker_pattern.finditer(text))
    if not matches:
        return []
    entries = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        normalized = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text[match.start():end])
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if len(normalized) >= 25:
            entries.append(normalized)
    return entries


def _split_author_year_references(text: str) -> list[str]:
    """Split author-year bibliographies at their year markers.

    Some two-column proceedings use author-year entries without a blank line
    between records after PDF text extraction. The year is the stable
    boundary in that format; stop before appendix content so it cannot be
    folded into the final citation.
    """
    appendix_match = re.search(
        r"(?im)(?:^\s*(?:appendix|supplementary material|additional ablation studies)\b"
        r"|additional details (?:are )?presented in appendix\b"
        r"|(?:•\s*)?(?:additional details|additional ablation studies|appendix)\b)",
        text,
    )
    bibliography = text[:appendix_match.start()] if appendix_match else text
    lines = bibliography.splitlines()
    starts: list[int] = []
    for index, line in enumerate(lines):
        candidate = " ".join(lines[index : index + 7])
        previous_line = lines[index - 1].strip() if index else ""
        if (
            _AUTHOR_YEAR_LINE_RE.match(line.strip())
            and not _AUTHOR_YEAR_NON_AUTHOR_PREFIX_RE.match(line.strip())
            and _AUTHOR_YEAR_MARKER_RE.search(candidate)
            and not previous_line.endswith((",", "and"))
        ):
            starts.append(index)
    if not starts:
        return []

    entries: list[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        normalized = re.sub(
            r"(?<=\w)-\s*\n\s*(?=\w)",
            "",
            "\n".join(lines[start:end]),
        )
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if len(normalized) >= 25:
            entries.append(normalized)
    return entries


def extract_references(structure_json: dict, raw_text: str) -> list[str]:
    """Extract up to 60 substantial references from a parsed paper."""
    sections = structure_json.get("sections") or {}
    reference_text = ""
    if isinstance(sections, dict):
        for name, section in sections.items():
            normalized_name = str(name).lower()
            if (
                "reference" in normalized_name
                or "bibliography" in normalized_name
                or "works cited" in normalized_name
                or "literature cited" in normalized_name
            ):
                reference_text = _section_text(section)
                break

    if not reference_text:
        matches = list(
            re.finditer(
                r"\b(?:references|bibliography|works\s+cited|literature\s+cited)\b",
                raw_text,
                re.IGNORECASE,
            )
        )
        if matches:
            reference_text = raw_text[matches[-1].end():]

    if not reference_text:
        return []

    references = _split_references(reference_text, _REFERENCE_MARKER_RE)
    if not references:
        references = _split_author_year_references(reference_text)
    if not references:
        references = _split_references(reference_text, _NUMBERED_REFERENCE_RE)
    if not references:
        references = _split_references(reference_text, _PLAIN_NUMBERED_REFERENCE_RE)
    if not references:
        references = [
            re.sub(r"\s+", " ", entry).strip()
            for entry in re.split(r"\n\s*\n+", reference_text)
            if len(re.sub(r"\s+", " ", entry).strip()) >= 25
        ]
    return references[:60]


def extract_reference_title(ref_text: str) -> str:
    """Extract the likely article title while retaining a full-text fallback."""
    cleaned = re.sub(r"^\s*(?:\[\d+\]|\d+[.)])\s*", "", ref_text).strip()
    year_match = _YEAR_RE.search(cleaned)
    if not year_match:
        return cleaned

    # Skip a disambiguation suffix such as the "a" in "2018a."
    title_region = re.sub(r"^[a-z]\b", "", cleaned[year_match.end():]).strip(" .,:;-")
    title_region = re.split(r"\bdoi\s*:", title_region, maxsplit=1, flags=re.IGNORECASE)[0]
    title_region = re.split(r"\barxiv\b", title_region, maxsplit=1, flags=re.IGNORECASE)[0]
    sentence_boundary = re.search(r"\.\s+(?=[A-Z])", title_region)
    title = title_region[:sentence_boundary.start()] if sentence_boundary else title_region
    title = re.sub(r"\s+", " ", title).strip(" .,:;")
    if not title:
        split = _authors_then_title(cleaned)
        if split:
            return split[1]
    return title or cleaned


# "I. J. Goodfellow, ..., and Y. Bengio. Maxout networks. arXiv:..., 2013."
# (CVPR/IEEE style): the year trails, so the author block ends at the first
# period after a full surname rather than at the year.
_AUTHOR_BLOCK_END_RE = re.compile(r"(?<=[A-Za-zÀ-ÿ][a-zà-ÿ])\.\s+(?=[A-Z0-9\"“])")
_TITLE_END_RE = re.compile(r"[.?!]\s+(?=[A-Z])|,?\s*\barxiv\s*:|[.?!]?\s*$", re.IGNORECASE)


def _authors_then_title(cleaned: str) -> tuple[str, str] | None:
    block_end = _AUTHOR_BLOCK_END_RE.search(cleaned)
    if not block_end:
        return None
    rest = cleaned[block_end.end():]
    title_end = _TITLE_END_RE.search(rest)
    title = rest[:title_end.start()] if title_end else rest
    if title_end and title_end.group(0)[:1] in "?!":
        title += title_end.group(0)[0]
    title = re.sub(r"\s+", " ", title).strip(" .,:;\"“”")
    if not title:
        return None
    return cleaned[:block_end.start()], title


def _normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    doi = re.sub(r"^\s*(?:https?://)?(?:dx\.)?doi\.org/", "", value, flags=re.IGNORECASE)
    doi = re.sub(r"^\s*doi:\s*", "", doi, flags=re.IGNORECASE)
    return doi.strip().rstrip(_TRAILING_DOI_PUNCTUATION).lower()


def extract_arxiv_id(raw_reference: str) -> str | None:
    """Extract and canonicalize a legacy or modern arXiv identifier."""
    match = re.search(
        r"(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/)"
        r"((?:\d{4}\.\d{4,5}|[a-z][\w.-]+/\d{7})(?:v\d+)?)",
        raw_reference,
        re.IGNORECASE,
    )
    if not match:
        return None
    return re.sub(
        r"v\d+$",
        "",
        match.group(1).rstrip(_TRAILING_DOI_PUNCTUATION),
        flags=re.IGNORECASE,
    )


def extract_isbn(raw_reference: str) -> str | None:
    """Extract and normalize an ISBN-10 or ISBN-13 from a citation."""
    for match in _ISBN_RE.finditer(raw_reference):
        value = re.sub(r"[-\s]", "", match.group(1)).upper()
        if _valid_isbn(value):
            return value
    return None


def _valid_isbn(value: str) -> bool:
    if len(value) == 10 and value[:-1].isdigit() and (
        value[-1].isdigit() or value[-1] == "X"
    ):
        return sum((10 - index) * (10 if digit == "X" else int(digit))
                   for index, digit in enumerate(value)) % 11 == 0
    if len(value) == 13 and value.isdigit() and value.startswith(("978", "979")):
        return sum((1 if index % 2 == 0 else 3) * int(digit)
                   for index, digit in enumerate(value)) % 10 == 0
    return False


def _surname(value: str) -> str:
    value = re.sub(r"\bet al\.?\b", "", value, flags=re.IGNORECASE)
    value = value.strip(" ,.;:")
    return _normalize_author_token(value).split(" ")[-1] if value else ""


def _normalize_author_token(value: str) -> str:
    """Canonicalize author text while preserving surname identity."""
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(
        _WORD_RE.findall(without_marks.casefold())
    )


def _reference_metadata(ref_text: str) -> ReferenceMetadata:
    cleaned = re.sub(r"^\s*(?:\[\d+\]|\(\d+\)|\d+[.)])\s*", "", ref_text).strip()
    year_match = _YEAR_RE.search(cleaned)
    year = int(year_match.group(0)) if year_match else None
    prefix = cleaned[:year_match.start()] if year_match else ""
    if year_match and not cleaned[year_match.end():].strip(" .,:;-"):
        split = _authors_then_title(cleaned)
        if split:
            prefix = split[0]
    author_parts = re.split(
        r"\s+(?:and|&)\s+|,\s*(?=[A-Z][a-z]+[-, ])|,\s*(?=[A-Z]\.)", prefix
    )
    surnames = []
    for part in author_parts:
        part = part.strip()
        words = re.findall(r"[A-Z][A-Za-zÀ-ÿ'’-]+", part)
        if words:
            # "Surname, I." leads with the surname; "First Last" and
            # "I. J. Last" end with it.
            leading = re.match(r"[A-Z][A-Za-zÀ-ÿ'’-]+,", part)
            surname = _surname(words[0] if leading else words[-1])
            if surname and surname not in surnames:
                surnames.append(surname)
    doi_match = _DOI_RE.search(cleaned)
    arxiv_id = extract_arxiv_id(cleaned)
    isbn = extract_isbn(cleaned)
    lower = cleaned.lower()
    jmlr = _is_jmlr_text(cleaned)
    neurips = _is_neurips_text(cleaned)
    document_type = "unknown"
    if arxiv_id:
        document_type = "preprint/arxiv"
    elif isbn:
        document_type = "book"
    elif re.search(
        r"\b(proceedings|conference|workshop|naacl|neurips|nips|inproceedings|ecml|acl|icml)\b",
        lower,
    ):
        document_type = "conference/proceedings"
    elif re.search(r"\b(press|publisher|mcgraw|mit press|springer|routledge)\b", lower):
        document_type = "book"
    elif jmlr or re.search(r"\b(journal|transactions|review|letters|science|sensors)\b", lower):
        document_type = "journal/article"
    title = extract_reference_title(ref_text)
    title = re.sub(r"\bdoi\s*:?.*$", "", title, flags=re.IGNORECASE).strip(" .,:;")
    tail = (
        re.sub(r"^[a-z]\b", "", cleaned[year_match.end():]).lstrip(" .,:;-")
        if year_match
        else cleaned
    )
    venue = None
    boundary = re.search(r"\.\s+(?=[A-Z])", tail)
    if boundary:
        venue = tail[boundary.end():].strip(" .,:;")
    publisher = venue if document_type == "book" else None
    if publisher:
        publisher = re.sub(r"\s*ISBN(?:-\d+)?\s*[:#]?\s*[\dXx-]+.*$", "", publisher, flags=re.IGNORECASE)
        publisher = publisher.strip(" .,:;") or None
        venue = publisher if document_type == "book" else venue
    volume, issue = _extract_jmlr_volume_issue(cleaned) if jmlr else (None, None)
    page_start, page_end = (
        _extract_page_range(cleaned) if (jmlr or neurips) else (None, None)
    )
    if jmlr:
        venue = _normalize_venue("Journal of Machine Learning Research")
    elif neurips:
        venue = _normalize_venue("NeurIPS")
        volume = _extract_neurips_volume(cleaned)
    return ReferenceMetadata(
        title=title,
        authors=author_parts,
        author_surnames=surnames,
        first_author=surnames[0] if surnames else None,
        year=year,
        doi=_normalize_doi(doi_match.group(0) if doi_match else None),
        arxiv_id=arxiv_id,
        venue=venue,
        publisher=publisher,
        isbn=isbn,
        document_type=document_type,
        volume=volume,
        issue=issue,
        page_start=page_start,
        page_end=page_end,
    )


def _normalize_venue(value: str | None) -> str | None:
    if not value:
        return None
    compact = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    if compact in {
        "jmlr",
        "journal of machine learning research",
        "j mach learn res",
    }:
        return "jmlr"
    if _is_neurips_text(value):
        return "neurips"
    return compact or None


def _is_jmlr_text(value: str) -> bool:
    return bool(
        re.search(
            r"(?<![a-z])jmlr(?![a-z])"
            r"|journal\s+of\s+machine\s+learning\s+research"
            r"|j\.?\s*mach\.?\s*learn\.?\s*res\.?",
            value,
            re.IGNORECASE,
        )
    )


def _is_neurips_text(value: str) -> bool:
    """Recognize the NeurIPS/NIPS proceedings family without broad keywords."""
    compact = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    return bool(
        re.search(r"(?<![a-z])(?:neurips|nips)(?![a-z])", compact)
        or re.search(
            r"\b(?:advances\s+in\s+)?neural\s+information\s+processing\s+systems\b",
            compact,
        )
        or re.search(r"\badv\.?\s+neural\s+inf\.?\s+process\.?\s+syst\.?\b", compact)
    )


def _extract_neurips_volume(text: str) -> int | None:
    if not _is_neurips_text(text):
        return None
    match = re.search(
        r"(?:neurips|nips|neural\s+information\s+processing\s+systems|"
        r"adv\.?\s+neural\s+inf\.?\s+process\.?\s+syst\.?)"
        r"[^0-9]{0,35}(?:volume\s*)?(\d{1,3})(?!\d)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    value = int(match.group(1))
    return None if 1900 <= value <= 2100 else value


def _extract_jmlr_volume_issue(text: str) -> tuple[int | None, int | None]:
    match = re.search(
        r"(?:jmlr|journal\s+of\s+machine\s+learning\s+research|"
        r"j\.?\s*mach\.?\s*learn\.?\s*res\.?)"
        r"[^0-9]{0,30}(?:volume\s*)?(\d{1,3})"
        r"(?:\s*\(\s*(\d{1,4})\s*\)|"
        r"\s*,?\s*volume\s+\d{1,3}\s*,?\s*issue\s+(\d{1,4}))?",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None, None
    volume = int(match.group(1))
    issue = next((int(value) for value in match.groups()[1:] if value), None)
    explicit_issue = re.search(r"\bissue\s+(\d{1,4})\b", text, re.IGNORECASE)
    if explicit_issue:
        issue = int(explicit_issue.group(1))
    if issue is None:
        suffix = text[match.end():match.end() + 12]
        colon = re.match(r"\s*:\s*(\d{1,3})(?!\d)", suffix)
        if colon and not re.match(r"\s*[-–−]", suffix[colon.end():]):
            issue = int(colon.group(1))
    return volume, issue


def _extract_page_range(text: str) -> tuple[int | None, int | None]:
    patterns = (
        r"(?:pp?\.?|pages?)\s*(\d{1,5})\s*[-–−]\s*(\d{1,5})",
        r"\b(\d{2,5})\s*[-–−]\s*(\d{2,5})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            if start <= end and start not in range(1900, 2100):
                return start, end
    return None, None


def normalize_title(text: str) -> str:
    """Normalize a title for case-, punctuation-, and dash-insensitive matching."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = re.sub(r"[\u2010-\u2015\u2212-]", " ", normalized)
    return " ".join(_WORD_RE.findall(normalized))


def _title_similarity(reference_title: str, candidate_title: str) -> float:
    reference = normalize_title(reference_title)
    candidate = normalize_title(candidate_title)
    if not reference or not candidate:
        return 0.0
    if reference == candidate:
        return 1.0
    reference_words = set(reference.split())
    candidate_words = set(candidate.split())
    jaccard = len(reference_words & candidate_words) / len(reference_words | candidate_words)
    sequence = SequenceMatcher(None, reference, candidate).ratio()
    length_ratio = min(len(reference_words), len(candidate_words)) / max(
        len(reference_words), len(candidate_words)
    )
    return max(jaccard, sequence * length_ratio)


def _candidate_authors(item: dict[str, Any]) -> list[str]:
    result = []
    for author in item.get("author") or []:
        family = _surname(str(author.get("family") or ""))
        if family:
            result.append(family)
    return result


def _document_type(item: dict[str, Any]) -> str:
    item_type = str(item.get("type") or "").lower()
    container = " ".join(item.get("container-title") or []).lower()
    doi = _normalize_doi(str(item.get("DOI") or ""))
    if doi and doi.startswith("10.48550/arxiv."):
        return "preprint/arxiv"
    if "book" in item_type or item_type in {"monograph"}:
        return "book"
    if "chapter" in item_type:
        return "chapter"
    if "proceedings" in item_type or "conference" in container:
        return "conference/proceedings"
    return "journal/article"


def _is_version_source(document_type: str) -> bool:
    return document_type in {"preprint/arxiv", "journal/article", "conference/proceedings"}


def _publication_relation(
    reference: ReferenceMetadata,
    item: dict[str, Any],
    title_score: float,
    author_score: float,
    matched_year: int | None,
) -> str:
    """Classify whether a located record is the cited publication or a version."""
    candidate_type = _document_type(item)
    candidate_authors = _candidate_authors(item)
    first_author_matches = _has_author_evidence(reference, item)
    if title_score < 0.8:
        return "different_work"
    if not reference.first_author or not candidate_authors:
        if reference.year is None or matched_year is None or reference.year == matched_year:
            return "exact"
        return "possible_related" if abs(reference.year - matched_year) <= 2 else "different_work"
    if not first_author_matches or author_score <= 0:
        return "different_work"
    if reference.year is None or matched_year is None or reference.year == matched_year:
        return "exact"

    year_difference = abs(reference.year - matched_year)
    source_pair = {
        reference.document_type,
        candidate_type,
    }
    plausible_source_version = (
        len(source_pair) > 1
        and all(_is_version_source(document_type) for document_type in source_pair)
        and (
            "preprint/arxiv" in source_pair
            or "conference/proceedings" in source_pair
        )
    )
    if plausible_source_version and year_difference <= 2:
        return "same_work_version"
    if year_difference <= 2 and author_score >= 0.5:
        return "possible_related"
    return "different_work"


def _type_relationship(reference: ReferenceMetadata, item: dict[str, Any]) -> str:
    if reference.document_type == "unknown":
        return "unknown"
    candidate_type = _document_type(item)
    if candidate_type == reference.document_type:
        return "compatible"
    if not item.get("type"):
        return "unknown"
    return "contradictory"


def _author_score(reference: ReferenceMetadata, item: dict[str, Any]) -> float:
    candidate = _candidate_authors(item)
    if not reference.author_surnames or not candidate:
        # Some Crossref records omit authors; do not treat absent metadata as
        # evidence against an otherwise strong title/year match.
        return 0.5
    if reference.first_author != candidate[0]:
        return 0.0
    return len(set(reference.author_surnames) & set(candidate)) / len(set(reference.author_surnames))


def _has_author_evidence(reference: ReferenceMetadata, item: dict[str, Any]) -> bool:
    """Require explicit first-author agreement for identifier verification."""
    candidate = _candidate_authors(item)
    return bool(
        reference.first_author
        and candidate
        and reference.first_author == candidate[0]
    )


def _year_score(reference_year: int | None, candidate_year: int | None) -> float:
    if reference_year is None or candidate_year is None:
        return 0.5
    difference = abs(reference_year - candidate_year)
    return 1.0 if difference == 0 else 0.6 if difference == 1 else 0.0


def _type_score(reference: ReferenceMetadata, item: dict[str, Any]) -> float:
    if reference.document_type == "unknown":
        return 0.5
    candidate_type = _document_type(item)
    return 1.0 if candidate_type == reference.document_type else 0.0


def _publisher_score(reference: ReferenceMetadata, item: dict[str, Any]) -> float:
    if not reference.publisher:
        return 0.5
    candidate = str(item.get("publisher") or "")
    if not candidate:
        return 0.5
    return _title_similarity(reference.publisher, candidate)


def _candidate_isbn(item: dict[str, Any]) -> str | None:
    values = item.get("ISBN") or item.get("isbn") or []
    if isinstance(values, str):
        values = [values]
    for value in values:
        normalized = extract_isbn(str(value))
        if normalized:
            return normalized
    return None


def _venue_score(reference: ReferenceMetadata, item: dict[str, Any]) -> float:
    if not reference.venue:
        return 0.5
    candidate_venue = " ".join(item.get("container-title") or [])
    if not candidate_venue:
        candidate_venue = str(item.get("publisher") or "")
    if not candidate_venue:
        return 0.5
    return _title_similarity(reference.venue, candidate_venue)


def _year_from_item(item: dict[str, Any]) -> int | None:
    for field in ("issued", "published-print", "published-online"):
        date_parts = (item.get(field) or {}).get("date-parts") or []
        if date_parts and date_parts[0] and isinstance(date_parts[0][0], int):
            return date_parts[0][0]
    return None


def _item_volume(item: dict[str, Any]) -> int | None:
    value = item.get("volume")
    return int(value) if str(value).isdigit() else None


def _item_issue(item: dict[str, Any]) -> int | None:
    value = item.get("issue") or item.get("article-number")
    return int(value) if str(value).isdigit() else None


def _item_pages(item: dict[str, Any]) -> tuple[int | None, int | None]:
    page = str(item.get("page") or "")
    match = re.search(r"(\d{1,5})\s*[-–−]\s*(\d{1,5})", page)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _jmlr_record_blocks(content: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(content, "html.parser")
    records = []
    for title_node in soup.find_all("dt"):
        detail_node = title_node.find_next_sibling("dd")
        if detail_node is None:
            continue
        abs_link = detail_node.find(
            "a",
            href=re.compile(r"/papers/v\d+/[^/\"']+\.html$", re.IGNORECASE),
        )
        if abs_link is None:
            continue

        title = " ".join(title_node.get_text(" ", strip=True).split())
        detail_text = " ".join(detail_node.get_text(" ", strip=True).split())
        author_node = detail_node.find(["b", "i"])
        author_text = (
            " ".join(author_node.get_text(" ", strip=True).split())
            if author_node is not None
            else ""
        )
        author_text = re.split(r"\s*;\s*", author_text, maxsplit=1)[0]
        authors = [
            {"family": _surname(part)}
            for part in re.split(r",|\band\b|&", author_text)
            if _surname(part)
        ]
        metadata_match = re.search(
            r"\((\d{1,4})\)\s*:\s*(\d{1,5})\s*[-–−]\s*(\d{1,5})"
            r"\s*,\s*((?:19|20)\d{2})\b",
            detail_text,
        )
        if metadata_match is None:
            continue
        href = str(abs_link.get("href") or "")
        volume_match = re.search(r"/papers/v(\d+)/", href, re.IGNORECASE)
        if volume_match is None:
            continue
        records.append(
            {
                "title": [title],
                "author": authors,
                "issued": {"date-parts": [[int(metadata_match.group(4))]]},
                "container-title": ["JMLR"],
                "type": "journal-article",
                "volume": volume_match.group(1),
                "issue": metadata_match.group(1),
                "page": f"{metadata_match.group(2)}-{metadata_match.group(3)}",
                "URL": (
                    href
                    if href.startswith(("http://", "https://"))
                    else f"{_JMLR_URL}{href}"
                ),
                "_source": "jmlr",
            }
        )
    if records:
        return records

    block_pattern = re.compile(
        r"<(?:li|tr|article|div|p)\b[^>]*>.*?</(?:li|tr|article|div|p)>",
        re.IGNORECASE | re.DOTALL,
    )
    for block in block_pattern.findall(content):
        link = re.search(
            r'<a\b[^>]*href=["\']([^"\']*?/papers/v\d+/[^"\']+\.html)["\'][^>]*>(.*?)</a>',
            block,
            re.IGNORECASE | re.DOTALL,
        )
        if not link:
            continue
        anchor_text = re.sub(r"<[^>]+>", " ", link.group(2))
        title = html.unescape(re.sub(r"\s+", " ", anchor_text)).strip()
        text = html.unescape(re.sub(r"<[^>]+>", " ", block))
        text = re.sub(r"\s+", " ", text).strip()
        authors = []
        author_match = re.search(r"(?:by|authors?:)\s*([^|;]+)", text, re.IGNORECASE)
        if author_match:
            author_text = author_match.group(1)
            year_in_authors = _YEAR_RE.search(author_text)
            if year_in_authors:
                author_text = author_text[:year_in_authors.start()]
            authors = [
                {"family": _surname(part)}
                for part in re.split(r",|\band\b|&", author_text)
                if _surname(part)
            ]
        year_match = _YEAR_RE.search(text)
        volume_match = re.search(r"/papers/v(\d+)/", link.group(1), re.IGNORECASE)
        if volume_match is None:
            volume_match = re.search(
                r"\b(?:volume\s*)?(\d{1,3})\s*(?:\((\d{1,4})\))?",
                text,
                re.IGNORECASE,
            )
        page_start, page_end = _extract_page_range(text)
        records.append(
            {
                "title": [title],
                "author": authors,
                "issued": {"date-parts": [[int(year_match.group(0))]]} if year_match else {},
                "container-title": ["JMLR"],
                "type": "journal-article",
                "volume": volume_match.group(1) if volume_match else None,
                "issue": (
                    (re.search(r"\bissue\s+(\d{1,4})\b", text, re.IGNORECASE)
                     or re.search(r"\b\d{1,3}\s*\((\d{1,4})\)", text)).group(1)
                    if (
                        re.search(r"\bissue\s+(\d{1,4})\b", text, re.IGNORECASE)
                        or re.search(r"\b\d{1,3}\s*\((\d{1,4})\)", text)
                    )
                    else None
                ),
                "page": f"{page_start}-{page_end}" if page_start is not None else "",
                "URL": (
                    link.group(1)
                    if link.group(1).startswith(("http://", "https://"))
                    else f"{_JMLR_URL}{link.group(1)}"
                ),
                "_source": "jmlr",
            }
        )
    return records


def _neurips_record_blocks(content: str, year: int) -> list[dict[str, Any]]:
    """Parse the current NeurIPS archive's title/author record structure."""
    soup = BeautifulSoup(content, "html.parser")
    book_title = soup.find(class_="book-title")
    volume_match = re.search(
        r"\b(?:volume\s*)?(\d{1,3})\s*$",
        book_title.get_text(" ", strip=True) if book_title is not None else "",
    )
    volume = volume_match.group(1) if volume_match else None
    records: list[dict[str, Any]] = []
    for title_node in soup.find_all("a", attrs={"title": "paper title"}):
        href = str(title_node.get("href") or "")
        if not re.search(r"/paper_files/paper/\d+/hash/[^/]+-Abstract\.html$", href):
            continue
        title = " ".join(title_node.get_text(" ", strip=True).split())
        if not title:
            continue
        author_node = title_node.find_next(
            "span", class_=re.compile(r"\bpaper-authors\b")
        )
        author_text = (
            " ".join(author_node.get_text(" ", strip=True).split())
            if author_node is not None
            else ""
        )
        authors = [
            {"family": _surname(part)}
            for part in re.split(r",|\band\b|&", author_text)
            if _surname(part)
        ]
        records.append(
            {
                "title": [title],
                "author": authors,
                "issued": {"date-parts": [[year]]},
                "container-title": ["NeurIPS"],
                "type": "proceedings-article",
                "volume": volume,
                "URL": (
                    href
                    if href.startswith(("http://", "https://"))
                    else f"{_NEURIPS_URL}{href}"
                ),
                "_source": "neurips",
            }
        )
    return records


async def _verify_by_neurips(
    client: httpx.AsyncClient,
    ref_text: str,
    metadata: ReferenceMetadata,
) -> dict[str, Any]:
    if metadata.year is None:
        return _result(ref_text, "not_found", source="neurips")
    cache = getattr(client, "_resense_neurips_cache", None)
    if cache is None:
        cache = {}
        setattr(client, "_resense_neurips_cache", cache)
    year = metadata.year
    if year not in cache:
        response = await _get_with_retries(
            client, _NEURIPS_YEAR_URL.format(year=year)
        )
        if response.status_code >= 400:
            result = _unavailable(
                ref_text,
                f"NeurIPS returned {response.status_code} {response.reason_phrase}",
            )
            cache[year] = result
            return result
        cache[year] = _neurips_record_blocks(response.text, year)
    candidates = cache[year]
    if isinstance(candidates, dict):
        return _result(
            ref_text,
            candidates["status"],
            error=candidates.get("error"),
            source="neurips",
        )
    if not candidates:
        return _result(ref_text, "not_found", source="neurips")

    ranked = []
    for item in candidates:
        title = (item.get("title") or [""])[0]
        matched_year = _year_from_item(item)
        title_score = _title_similarity(metadata.title, title)
        author_score = _author_score(metadata, item)
        year_score = _year_score(metadata.year, matched_year)
        volume_score = (
            0.5
            if metadata.volume is None
            else 1.0
            if _item_volume(item) in (None, metadata.volume)
            else 0.0
        )
        ranked.append(
            (title_score, author_score, year_score, volume_score, item, matched_year)
        )
    title_score, author_score, year_score, volume_score, item, matched_year = max(
        ranked, key=lambda candidate: candidate[:4]
    )
    conflict_fields = []
    if title_score >= 0.5:
        if metadata.author_surnames and not _has_author_evidence(metadata, item):
            conflict_fields.append("first_author")
        if metadata.year is not None and matched_year != metadata.year:
            conflict_fields.append("year")
        if metadata.volume is not None and volume_score == 0.0:
            conflict_fields.append("volume")
        candidate_start, candidate_end = _item_pages(item)
        if (
            metadata.page_start is not None
            and candidate_start is not None
            and (metadata.page_start, metadata.page_end)
            != (candidate_start, candidate_end)
        ):
            conflict_fields.append("pages")

    exact = (
        title_score >= 0.9
        and _has_author_evidence(metadata, item)
        and (metadata.year is None or matched_year == metadata.year)
        and (metadata.volume is None or volume_score == 1.0)
    )
    status = "verified" if exact else "uncertain" if title_score >= 0.5 else "not_found"
    return _result(
        ref_text,
        status,
        title_score,
        (item.get("title") or [""])[0] or None,
        _normalize_doi(str(item.get("DOI") or "")),
        matched_year,
        title_score=title_score,
        author_score=author_score,
        year_score=year_score,
        volume_score=volume_score,
        publication_relation="exact" if exact else "possible_related",
        official_url=item.get("URL"),
        source="neurips",
        match_reason=(
            "exact NeurIPS publication metadata match"
            if exact
            else "NeurIPS metadata is incomplete or conflicting"
        ),
        conflict_fields=conflict_fields,
    )


async def _verify_by_jmlr(
    client: httpx.AsyncClient,
    ref_text: str,
    metadata: ReferenceMetadata,
) -> dict[str, Any]:
    if metadata.volume is None:
        return _result(ref_text, "not_found", source="jmlr")
    cache = getattr(client, "_resense_jmlr_cache", None)
    if cache is None:
        cache = {}
        setattr(client, "_resense_jmlr_cache", cache)
    key = metadata.volume
    if key not in cache:
        response = await _get_with_retries(
            client,
            _JMLR_VOLUME_URL.format(volume=metadata.volume),
        )
        if response.status_code >= 400:
            result = _unavailable(
                ref_text,
                f"JMLR returned {response.status_code} {response.reason_phrase}",
            )
            cache[key] = result
            return result
        cache[key] = _jmlr_record_blocks(response.text)
    candidates = cache[key]
    if isinstance(candidates, dict):
        return _result(ref_text, candidates["status"], error=candidates.get("error"), source="jmlr")
    ranked = []
    for item in candidates:
        title = (item.get("title") or [""])[0]
        matched_year = _year_from_item(item)
        title_score = _title_similarity(metadata.title, title)
        author_score = _author_score(metadata, item)
        volume_score = 1.0 if metadata.volume == _item_volume(item) else 0.0
        issue = _item_issue(item)
        page_start, page_end = _item_pages(item)
        page_score = (
            1.0
            if metadata.page_start is None
            or (metadata.page_start == page_start and metadata.page_end == page_end)
            else 0.0
        )
        issue_score = 1.0 if metadata.issue is None or metadata.issue == issue else 0.0
        year_score = _year_score(metadata.year, matched_year)
        ranked.append((title_score, author_score, year_score, volume_score, page_score, issue_score, item, matched_year))
    if not ranked:
        return _result(ref_text, "not_found", source="jmlr")
    title_score, author_score, year_score, volume_score, page_score, issue_score, item, matched_year = max(
        ranked, key=lambda candidate: candidate[:6]
    )
    conflict_fields = []
    if title_score >= 0.5:
        if metadata.author_surnames and not _has_author_evidence(metadata, item):
            conflict_fields.append("first_author")
        if metadata.year is not None and matched_year is not None and matched_year != metadata.year:
            conflict_fields.append("year")
        if metadata.volume is not None and volume_score == 0.0:
            conflict_fields.append("volume")
        if metadata.page_start is not None and page_score == 0.0:
            conflict_fields.append("pages")
        if metadata.issue is not None and issue_score == 0.0:
            conflict_fields.append("issue")
    exact = (
        title_score >= 0.9
        and _has_author_evidence(metadata, item)
        and (metadata.year is None or matched_year == metadata.year)
        and (metadata.volume is None or volume_score == 1.0)
        and (metadata.page_start is None or page_score == 1.0)
        and (metadata.issue is None or issue_score == 1.0)
    )
    status = "verified" if exact else "uncertain" if title_score >= 0.5 else "not_found"
    return _result(
        ref_text,
        status,
        title_score,
        (item.get("title") or [""])[0] or None,
        _normalize_doi(str(item.get("DOI") or "")),
        matched_year,
        title_score=title_score,
        author_score=author_score,
        year_score=year_score,
        volume_score=volume_score,
        issue_score=issue_score,
        page_score=page_score,
        publication_relation="exact" if exact else "possible_related",
        official_url=item.get("URL"),
        source="jmlr",
        match_reason="exact JMLR publication metadata match" if exact else "JMLR metadata is incomplete or conflicting",
        conflict_fields=conflict_fields,
    )


def _result(
    raw: str,
    status: str,
    similarity: float = 0.0,
    title: str | None = None,
    doi: str | None = None,
    year: int | None = None,
    error: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    result = {
        "raw": raw,
        "status": status,
        "similarity": similarity,
        "matched_title": title,
        "matched_doi": doi,
        "matched_year": year,
        "error": error,
    }
    result.update(extra)
    return result


async def _get_with_retries(
    client: httpx.AsyncClient, url: str, params: dict[str, Any] | None = None
) -> httpx.Response:
    pacer = _pacer_for(client, url)
    host = httpx.URL(url).host
    last_response: httpx.Response | None = None
    last_error: Exception | None = None
    if pacer.unavailable_reason:
        raise httpx.TransportError(pacer.unavailable_reason)
    for attempt in range(_MAX_ATTEMPTS):
        try:
            async with pacer:
                response = await client.get(url, params=params)
            last_response = response
            if response.status_code not in (429,) and response.status_code < 500:
                pacer.record_success()
                return response
            delay = _retry_delay(response, attempt)
            if response.status_code == 429:
                retry_after = _retry_after(response)
                if retry_after is not None and retry_after > _MAX_RETRY_DELAY:
                    # The provider wants us gone for longer than a report can
                    # wait (e.g. a daily quota); stop calling it this run.
                    pacer.give_up(f"{host}: rate limited, Retry-After {retry_after:.0f}s")
                    return response
                pacer.cool_down(delay)
            if attempt == _MAX_ATTEMPTS - 1:
                break
            logger.warning(
                "%s returned %s; retry %d/%d in %.1fs",
                host,
                response.status_code,
                attempt + 1,
                _MAX_ATTEMPTS,
                delay,
            )
            await asyncio.sleep(delay)
        except httpx.TransportError as exc:
            last_error = exc
            if attempt == _MAX_ATTEMPTS - 1:
                break
            await asyncio.sleep(_retry_delay(None, attempt))

    if last_response is not None:
        return last_response
    pacer.record_failure(host)
    raise httpx.TransportError(f"{host} request failed after retries") from last_error


def _unavailable(raw: str, detail: str) -> dict[str, Any]:
    return _result(raw, "unavailable", error=detail)


def _verify_doi_metadata(
    ref_text: str,
    metadata: ReferenceMetadata,
    item: dict[str, Any],
) -> dict[str, Any]:
    """Classify a direct DOI record using bibliographic evidence, not a blend score."""
    matched_title = (item.get("title") or [""])[0] or None
    matched_year = _year_from_item(item)
    title_score = _title_similarity(metadata.title, matched_title or "")
    author_score = _author_score(metadata, item)
    year_score = _year_score(metadata.year, matched_year)
    venue_score = _venue_score(metadata, item)
    type_score = _type_score(metadata, item)
    doi_score = (
        1.0
        if _normalize_doi(str(item.get("DOI") or "")) == metadata.doi
        else 0.0
    )
    year_matches = metadata.year is None or matched_year is None or year_score == 1.0
    author_matches = _has_author_evidence(metadata, item)
    if doi_score == 1.0 and title_score >= 0.8 and author_matches and year_matches:
        # A direct DOI match with corroborating title, author, and year
        # evidence is authoritative. Generic type/venue heuristics must not
        # downgrade it.
        status = "verified"
    elif title_score >= 0.5:
        status = "uncertain"
    else:
        status = "not_found"
    logger.info(
        "Reference verification: title=%r first_author=%r year=%r doi=%r "
        "candidate_title=%r candidate_author=%r candidate_year=%r "
        "doi_score=%.3f title_score=%.3f author_score=%.3f year_score=%.3f "
        "venue_score=%.3f type_score=%.3f status=%s source=doi",
        metadata.title,
        metadata.first_author,
        metadata.year,
        metadata.doi,
        matched_title,
        (_candidate_authors(item) or [None])[0],
        matched_year,
        doi_score,
        title_score,
        author_score,
        year_score,
        venue_score,
        type_score,
        status,
    )
    return _result(
        ref_text,
        status,
        title_score,
        matched_title,
        _normalize_doi(str(item.get("DOI") or "")) or metadata.doi,
        matched_year,
        title_score=title_score,
        author_score=author_score,
        author_matches=author_matches,
        year_score=year_score,
        venue_score=venue_score,
        type_score=type_score,
        doi_score=doi_score,
        match_reason=(
            "exact DOI with strong title, author, and year agreement"
            if status == "verified"
            else "DOI record has incomplete or conflicting bibliographic evidence"
        ),
        source="crossref",
    )


def _parse_arxiv_record(content: str, arxiv_id: str) -> dict[str, Any] | None:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"arXiv response could not be parsed: {exc}") from exc
    namespace = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    entry = root.find("atom:entry", namespace)
    if entry is None:
        return None
    title = " ".join((entry.findtext("atom:title", default="", namespaces=namespace)).split())
    authors = [
        {"family": name.rsplit(" ", 1)[-1], "given": name.rsplit(" ", 1)[0]}
        for name in (
            " ".join((author.findtext("atom:name", default="", namespaces=namespace)).split())
            for author in entry.findall("atom:author", namespace)
        )
        if name
    ]
    published = entry.findtext("atom:published", default="", namespaces=namespace)
    year_match = re.match(r"(\d{4})", published)
    record: dict[str, Any] = {
        "title": [title],
        "author": authors,
        "issued": {"date-parts": [[int(year_match.group(1))]]} if year_match else {},
        "arxiv_id": arxiv_id,
    }
    doi = entry.findtext("arxiv:doi", default="", namespaces=namespace)
    if doi:
        record["DOI"] = _normalize_doi(doi)
    journal_ref = entry.findtext("arxiv:journal_ref", default="", namespaces=namespace)
    if journal_ref:
        record["container-title"] = [journal_ref]
    return record


def _verify_arxiv_metadata(
    ref_text: str,
    metadata: ReferenceMetadata,
    item: dict[str, Any],
) -> dict[str, Any]:
    matched_title = (item.get("title") or [""])[0] or None
    matched_year = _year_from_item(item)
    title_score = _title_similarity(metadata.title, matched_title or "")
    author_score = _author_score(metadata, item)
    year_score = _year_score(metadata.year, matched_year)
    year_matches = metadata.year is None or matched_year is None or year_score >= 0.6
    if title_score >= 0.9 and author_score > 0 and year_matches:
        status = "verified"
    elif title_score >= 0.5:
        status = "uncertain"
    else:
        status = "not_found"
    return _result(
        ref_text,
        status,
        title_score,
        matched_title,
        _normalize_doi(str(item.get("DOI") or "")),
        matched_year,
        title_score=title_score,
        author_score=author_score,
        year_score=year_score,
        venue_score=0.5,
        type_score=0.5,
        arxiv_id=metadata.arxiv_id,
        match_reason=(
            "arXiv identifier with strong title, author, and year agreement"
            if status == "verified"
            else "arXiv record has incomplete or conflicting bibliographic evidence"
        ),
        source="arxiv",
    )


async def _verify_by_arxiv(
    client: httpx.AsyncClient,
    ref_text: str,
    metadata: ReferenceMetadata,
) -> dict[str, Any]:
    response = await _get_with_retries(
        client,
        _ARXIV_API_URL,
        params={"id_list": metadata.arxiv_id},
    )
    if response.status_code == 404:
        return _result(ref_text, "not_found")
    if response.status_code >= 400:
        return _unavailable(
            ref_text,
            f"arXiv returned {response.status_code} {response.reason_phrase}",
        )
    item = _parse_arxiv_record(response.text, metadata.arxiv_id or "")
    if item is None:
        return _result(ref_text, "not_found")
    return _verify_arxiv_metadata(ref_text, metadata, item)


def _openalex_record(work: dict[str, Any]) -> dict[str, Any]:
    authors = []
    for authorship in work.get("authorships") or []:
        author = authorship.get("author") or {}
        display_name = str(author.get("display_name") or "")
        parts = display_name.rsplit(" ", 1)
        if display_name:
            authors.append(
                {
                    "family": parts[-1],
                    "given": parts[0] if len(parts) > 1 else "",
                }
            )
    source = work.get("primary_location", {}).get("source") or {}
    record: dict[str, Any] = {
        "title": [str(work.get("title") or "")],
        "author": authors,
        "issued": {"date-parts": [[work["publication_year"]]]}
        if work.get("publication_year")
        else {},
        "container-title": [str(source.get("display_name") or "")],
        "publisher": str(source.get("host_organization_name") or ""),
        "type": str(work.get("type") or ""),
        "DOI": _normalize_doi(str(work.get("doi") or "")),
    }
    openalex_isbn = (work.get("ids") or {}).get("isbn")
    if openalex_isbn:
        record["isbn"] = [openalex_isbn] if isinstance(openalex_isbn, str) else openalex_isbn
    return record


def _candidate_result(
    ref_text: str,
    metadata: ReferenceMetadata,
    item: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    matched_title = (item.get("title") or [""])[0] or None
    matched_year = _year_from_item(item)
    title_score = _title_similarity(metadata.title, matched_title or "")
    author_score = _author_score(metadata, item)
    year_score = _year_score(metadata.year, matched_year)
    venue_score = _venue_score(metadata, item)
    type_score = _type_score(metadata, item)
    publisher_score = _publisher_score(metadata, item)
    isbn_match = bool(metadata.isbn and metadata.isbn == _candidate_isbn(item))
    year_matches = metadata.year is None or matched_year is None or year_score == 1.0
    publication_relation = _publication_relation(
        metadata, item, title_score, author_score, matched_year
    )
    if metadata.document_type == "book":
        final_score = (
            title_score * 0.40
            + author_score * 0.20
            + year_score * 0.15
            + publisher_score * 0.15
            + type_score * 0.10
        )
        if isbn_match:
            final_score = 1.0
        if type_score == 0.0:
            status = "not_found"
        elif isbn_match and title_score >= 0.8 and author_score > 0 and year_matches:
            status = "verified"
        elif title_score >= 0.8 and author_score > 0 and year_matches and final_score >= 0.70:
            status = "verified" if not metadata.isbn else "uncertain"
        elif title_score >= 0.5 and final_score >= 0.45:
            status = "uncertain"
        else:
            status = "not_found"
    else:
        final_score = (
            title_score * 0.45
            + author_score * 0.25
            + year_score * 0.15
            + venue_score * 0.10
            + type_score * 0.05
        )
        type_conflict = (
            metadata.document_type != "unknown"
            and type_score == 0.0
            and publication_relation not in {"same_work_version", "possible_related"}
        )
        author_identity_confirmed = (
            not metadata.author_surnames
            or _has_author_evidence(metadata, item)
        )
        if (
            publication_relation == "exact"
            and title_score >= 0.8
            and author_score > 0
            and author_identity_confirmed
            and year_matches
            and not type_conflict
            and final_score >= 0.72
        ):
            status = "verified"
        elif (
            publication_relation == "exact"
            and title_score >= 0.5
            and not author_identity_confirmed
        ):
            status = "uncertain"
        elif publication_relation in {"same_work_version", "possible_related"}:
            status = "uncertain"
        elif publication_relation == "different_work":
            status = "not_found"
        elif title_score >= 0.5 and final_score >= 0.45:
            status = "uncertain"
        else:
            status = "not_found"
    return _result(
        ref_text,
        status,
        title_score,
        matched_title,
        _normalize_doi(str(item.get("DOI") or "")),
        matched_year,
        title_score=title_score,
        author_score=author_score,
        year_score=year_score,
        venue_score=venue_score,
        type_score=type_score,
        publisher_score=publisher_score,
        isbn_match=isbn_match,
        final_score=final_score,
        publication_relation=publication_relation,
        source=source,
        match_reason="strong multi-signal bibliographic agreement"
        if status == "verified"
        else (
            "matching record has incomplete author metadata"
            if publication_relation == "exact"
            else (
            "same scholarly work found as a different preprint/publication version"
            if publication_relation == "same_work_version"
            else (
                "same title but conflicting author/year metadata"
                if publication_relation == "different_work"
                else "possible related scholarly work with a different publication year"
            )
            )
        )
    )


async def _verify_by_openalex(
    client: httpx.AsyncClient,
    ref_text: str,
    metadata: ReferenceMetadata,
    mailto: str,
) -> dict[str, Any]:
    params = {
        "search": metadata.title[:300],
        "per-page": 10,
    }
    if mailto:
        params["mailto"] = mailto
    response = await _get_with_retries(client, _OPENALEX_URL, params=params)
    if response.status_code >= 400:
        return _unavailable(
            ref_text,
            f"OpenAlex returned {response.status_code} {response.reason_phrase}",
        )
    try:
        payload = response.json()
    except (ValueError, TypeError) as exc:
        return _unavailable(ref_text, f"OpenAlex response could not be parsed: {exc}")
    works = []
    if isinstance(payload, dict):
        works = payload.get("results") or []
    elif isinstance(payload, list):
        works = payload
    if not works:
        return _result(ref_text, "not_found", source="openalex")
    candidates: list[dict[str, Any]] = []
    for work in works:
        if not isinstance(work, dict):
            continue
        try:
            candidates.append(
                _candidate_result(ref_text, metadata, _openalex_record(work), "openalex")
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("OpenAlex record could not be processed: %s", exc)
            continue
    if not candidates:
        return _result(ref_text, "not_found", source="openalex")
    return max(
        candidates,
        key=lambda result: (result.get("final_score", 0.0), result.get("similarity", 0.0)),
    )


async def _verify_reference_primary(client: httpx.AsyncClient, ref_text: str, mailto: str) -> dict:
    """Verify one reference against Crossref without raising network errors."""
    metadata = _reference_metadata(ref_text)
    try:
        if metadata.doi:
            response = await _get_with_retries(client, f"{_CROSSREF_URL}/works/{metadata.doi}")
            if response.status_code == 404:
                return _result(ref_text, "not_found")
            if response.status_code >= 400:
                return _unavailable(
                    ref_text,
                    f"Crossref returned {response.status_code} {response.reason_phrase}",
                )
            item = response.json().get("message") or {}
            if not item:
                return _result(ref_text, "not_found")
            return _verify_doi_metadata(ref_text, metadata, item)
        if metadata.arxiv_id:
            return await _verify_by_arxiv(client, ref_text, metadata)
        else:
            if _is_jmlr_text(ref_text):
                jmlr_result = await _verify_by_jmlr(client, ref_text, metadata)
                if jmlr_result.get("status") == "verified":
                    return jmlr_result
                if jmlr_result.get("conflict_fields"):
                    return jmlr_result
            if _is_neurips_text(ref_text):
                neurips_result = await _verify_by_neurips(client, ref_text, metadata)
                if neurips_result.get("status") == "verified":
                    return neurips_result
                if neurips_result.get("conflict_fields"):
                    return neurips_result
            response = await _get_with_retries(
                client,
                f"{_CROSSREF_URL}/works",
                params={
                    "query.bibliographic": f"{metadata.title} {metadata.first_author or ''}"[:300],
                    "rows": 5,
                    **({"mailto": mailto} if mailto else {}),
                },
            )
            if response.status_code >= 400:
                return _unavailable(
                    ref_text,
                    f"Crossref returned {response.status_code} {response.reason_phrase}",
                )
            candidates = response.json().get("message", {}).get("items", [])
            if not candidates:
                return _result(ref_text, "not_found")

        if metadata.document_type == "book":
            book_results = [
                _candidate_result(ref_text, metadata, item, "crossref")
                for item in candidates
            ]
            return max(
                book_results,
                key=lambda result: (
                    result.get("final_score", 0.0),
                    result.get("similarity", 0.0),
                ),
            )

        ranked = []
        for item in candidates:
            title = (item.get("title") or [""])[0] or ""
            year = _year_from_item(item)
            title_score = _title_similarity(metadata.title, title)
            author_score = _author_score(metadata, item)
            year_score = _year_score(metadata.year, year)
            type_score = _type_score(metadata, item)
            venue_score = _venue_score(metadata, item)
            total_score = (
                title_score * 0.40
                + author_score * 0.25
                + year_score * 0.15
                + venue_score * 0.10
                + type_score * 0.10
            )
            ranked.append(
                (
                    total_score,
                    title_score,
                    author_score,
                    year_score,
                    venue_score,
                    type_score,
                    item,
                    year,
                )
            )
        (
            total_score,
            similarity,
            author_score,
            year_score,
            venue_score,
            type_score,
            item,
            matched_year,
        ) = max(
            ranked, key=lambda candidate: (candidate[0], candidate[1], candidate[2])
        )
        matched_title = (item.get("title") or [""])[0] or None
        first_author_matches = author_score > 0
        year_matches = metadata.year is None or matched_year is None or year_score == 1.0
        type_relationship = _type_relationship(metadata, item)
        publication_relation = _publication_relation(
            metadata, item, similarity, author_score, matched_year
        )
        author_identity_confirmed = (
            not metadata.author_surnames
            or _has_author_evidence(metadata, item)
        )
        material_metadata_conflict = (
            type_relationship == "contradictory"
            and publication_relation not in {"same_work_version", "possible_related"}
        )
        if (
            publication_relation == "exact"
            and similarity >= 0.95
            and first_author_matches
            and author_identity_confirmed
            and year_matches
            and not material_metadata_conflict
        ):
            status = "verified"
        elif (
            publication_relation == "exact"
            and similarity >= 0.5
            and not author_identity_confirmed
        ):
            status = "uncertain"
        elif publication_relation in {"same_work_version", "possible_related"}:
            status = "uncertain"
        elif publication_relation == "different_work":
            status = "not_found"
        elif (
            similarity >= 0.5
            and total_score >= 0.45
        ):
            status = "uncertain"
        else:
            status = "not_found"
        logger.info(
            "Reference verification: title=%r first_author=%r year=%r doi=%r "
            "candidate_title=%r candidate_author=%r candidate_year=%r "
            "title_score=%.3f author_score=%.3f year_score=%.3f type_score=%.3f "
            "final_score=%.3f status=%s source=crossref",
            metadata.title,
            metadata.first_author,
            metadata.year,
            metadata.doi,
            matched_title,
            (_candidate_authors(item) or [None])[0],
            matched_year,
            similarity,
            author_score,
            year_score,
            type_score,
            total_score,
            status,
        )
        return _result(
            ref_text,
            status,
            similarity,
            matched_title,
            item.get("DOI"),
            matched_year,
            title_score=similarity,
            author_score=author_score,
            year_score=year_score,
            venue_score=venue_score,
            type_score=type_score,
            publication_relation=publication_relation,
            match_reason=(
                "strong title, author, year, and type agreement"
                if status == "verified"
                else (
                    "matching record has incomplete author metadata"
                    if publication_relation == "exact"
                    else (
                    "same scholarly work found as a different preprint/publication version"
                    if publication_relation == "same_work_version"
                    else (
                        "same title but conflicting author/year metadata"
                        if publication_relation == "different_work"
                        else "possible related scholarly work with a different publication year"
                    )
                    )
                )
            ),
            source="crossref",
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        logger.warning("Crossref reference verification unavailable: %s", exc)
        return _unavailable(ref_text, f"Crossref response could not be processed: {exc}")


async def verify_reference(client: httpx.AsyncClient, ref_text: str, mailto: str) -> dict:
    """Verify identifiers directly, then use Crossref with OpenAlex fallback."""
    metadata = _reference_metadata(ref_text)
    primary = await _verify_reference_primary(client, ref_text, mailto)
    if metadata.doi or metadata.arxiv_id or primary.get("status") == "verified":
        return primary

    try:
        openalex = await _verify_by_openalex(client, ref_text, metadata, mailto)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        logger.warning("OpenAlex reference verification unavailable: %s", exc)
        openalex = _unavailable(ref_text, f"OpenAlex response could not be processed: {exc}")
    if primary.get("status") == "unavailable" and openalex.get("status") == "unavailable":
        return _unavailable(
            ref_text,
            f"Crossref unavailable; {openalex.get('error', 'OpenAlex unavailable')}",
        )
    if primary.get("conflict_fields"):
        return primary
    if openalex.get("status") == "verified":
        return openalex
    if primary.get("status") == "uncertain" and openalex.get("status") == "not_found":
        return primary
    if openalex.get("status") == "uncertain" and primary.get("status") == "not_found":
        return openalex
    if primary.get("status") == "uncertain" and openalex.get("status") == "uncertain":
        return max(
            (primary, openalex),
            key=lambda result: (
                result.get("final_score", result.get("similarity", 0.0)),
                result.get("similarity", 0.0),
            ),
        )
    return openalex if openalex.get("status") != "not_found" else primary


async def verify_all(refs: list[str], mailto: str) -> list[dict]:
    """Verify references with one shared client and polite concurrency."""
    headers = {"User-Agent": f"ReSense/1.0 (mailto:{mailto})"} if mailto else {}
    # Per-host pacers below enforce each provider's limits; this only bounds
    # how many references are in flight at once.
    semaphore = asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        _CLIENT_PACERS[client] = _provider_pacers(polite=bool(mailto))
        async def verify(index: int, reference: str) -> dict:
            async with semaphore:
                try:
                    result = await verify_reference(client, reference, mailto)
                except Exception as exc:
                    # One bad reference must never discard the rest of the report.
                    logger.warning("Reference verification failed for index %d: %s", index, exc)
                    result = _unavailable(reference, f"Reference verification failed: {exc}")
                return {"index": index, **result}

        results = await asyncio.gather(
            *(verify(index, reference) for index, reference in enumerate(refs, start=1))
        )
        return [dict(item) for item in results]
