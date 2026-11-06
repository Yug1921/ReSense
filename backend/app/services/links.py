"""
Reproducibility check: do the paper's links still work, and is its data or
code actually shared, or only promised "on request"?

Links are read from the paper's text, tested with a light request each, and
sorted into working, broken (the page or the whole site is gone) and
unconfirmed (the site blocks automatic checks or didn't answer in time).
Only public web addresses are fetched: anything that resolves to a private,
local or reserved address is skipped, so a crafted paper can't make the
server probe its own network.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

logger = logging.getLogger(__name__)

MAX_LINKS = 80
_TIMEOUT = httpx.Timeout(10.0, connect=6.0)
_MAX_REDIRECTS = 5
_HEADERS = {
    # Many sites refuse requests that don't look like a browser.
    "User-Agent": "Mozilla/5.0 (compatible; ReSense link checker; +https://github.com/Yug1921/ReSense)",
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
}

# A URL broken across lines in the PDF: "https://github.com/foo/" + "bar".
# A line ending in "." is a finished sentence, and a lone "and" is prose.
_WRAPPED_URL_RE = re.compile(
    r"((?:https?://|www\.)\S*[/\-_=&?#~])\n(?!(?:and|or|the|in|of|to|for|see|at|is|are)\b)(?=[\w/%#~-])"
)
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"'{}|\\^`\[\]]+", re.IGNORECASE)
_TRAILING = ".,;:!?'\"’”)]}>"


def _clean_url(url: str) -> str | None:
    url = url.strip()
    # The next sentence glued on after a full stop: "leaderboard).The".
    path_start = url.find("/", url.find("//") + 2)
    if path_start != -1:
        glued = re.search(r"\.(?=[A-Z][a-z]{2,})", url[path_start:])
        if glued:
            url = url[: path_start + glued.start()]
    while url and url[-1] in _TRAILING:
        # Keep a closing bracket that belongs to the URL ("wiki/Foo_(bar)").
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            break
        url = url[:-1]
    if url.lower().startswith("www."):
        url = "http://" + url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or "." not in parts.hostname:
        return None
    return url


def extract_links(raw_text: str, references_start: int | None = None) -> list[dict[str, Any]]:
    """Unique web links in reading order, each marked as in the body or the references."""
    text = raw_text or ""
    while True:  # a long URL can wrap over several lines
        joined = _WRAPPED_URL_RE.sub(r"\1", text)
        if joined == text:
            break
        text = joined
    shift = len(raw_text or "") - len(text)  # joining lines only removes characters
    links: dict[str, dict[str, Any]] = {}
    for match in _URL_RE.finditer(text):
        url = _clean_url(match.group(0))
        if not url:
            continue
        key = url.rstrip("/").lower()
        if key in links:
            continue
        in_refs = references_start is not None and match.start() + shift >= references_start
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        context = re.sub(r"\s+", " ", text[line_start : line_end if line_end != -1 else None]).strip()
        links[key] = {"url": url, "where": "references" if in_refs else "body", "context": context[:220]}
        if len(links) >= MAX_LINKS:
            break
    return list(links.values())


# --------------------------------------------------------------- statements

# A new sentence, or a numbered heading run into the text ("... bert. 2 Related Work").
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[]|\d{1,2}(?:\.\d{1,2})*\s+[A-Z][a-z])")
_SUBJECT = r"(?:data(?:sets?)?|code|source code|software|materials?|(?:pre-?trained\s+)?models|scripts?|implementation|recordings|samples)"
_ON_REQUEST_RE = re.compile(
    rf"\b{_SUBJECT}\b[^.]{{0,160}}\b(?:up)?on\s+(?:reasonable\s+|written\s+|justified\s+)?request\b"
    r"|\b(?:up)?on\s+(?:reasonable\s+)?request\b[^.]{0,80}\b" + _SUBJECT + r"\b"
    r"|\bavailable\s+from\s+the\s+(?:corresponding\s+)?authors?\b"
    r"|\bcontact\s+the\s+(?:corresponding\s+)?authors?\b[^.]{0,60}\b" + _SUBJECT + r"\b",
    re.IGNORECASE,
)
_SHARED_RE = re.compile(
    rf"\b{_SUBJECT}\b[^.]{{0,120}}\b(?:is|are|will be|has been|have been|were|was|made)\s+"
    r"(?:made\s+)?(?:publicly\s+|freely\s+|openly\s+)?(?:available|released|accessible|deposited|shared)\b",
    re.IGNORECASE,
)
_WHERE_RE = re.compile(r"https?://|www\.|\b(?:github|gitlab|zenodo|figshare|osf\.io|hugging\s?face|dryad|kaggle)\b", re.IGNORECASE)
_NEGATED_RE = re.compile(r"\b(?:not|never|no longer)\s+(?:\w+\s+){0,2}(?:publicly\s+)?available\b", re.IGNORECASE)


def _sentences(text: str) -> list[str]:
    flat = re.sub(r"-\n(?=[a-z])", "", text)
    flat = re.sub(r"\s+", " ", flat)
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(flat) if s.strip()]


def availability_statements(body_text: str, limit: int = 12) -> list[dict[str, str]]:
    """Sentences saying where data or code can be found, or that it is only "on request"."""
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for sentence in _sentences(body_text):
        if len(sentence) > 600:
            continue
        if _ON_REQUEST_RE.search(sentence):
            kind = "on_request"
        elif _SHARED_RE.search(sentence) and _WHERE_RE.search(sentence) and not _NEGATED_RE.search(sentence):
            kind = "public"  # says it is shared, and where
        else:
            kind = None
        if not kind:
            continue
        key = sentence.lower()[:120]
        if key in seen:
            continue
        seen.add(key)
        found.append({"kind": kind, "text": sentence[:400]})
        if len(found) >= limit:
            break
    # Promises "on request" are the ones a reader needs to see first.
    return sorted(found, key=lambda item: item["kind"] != "on_request")


# --------------------------------------------------------------- checking


class _Blocked(Exception):
    pass


def _public_host(host: str) -> bool:
    """True when every address the host resolves to is a public one."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        if not address.is_global:
            return False
    return bool(infos)


async def _resolve_public(host: str) -> None:
    try:
        public = await asyncio.to_thread(_public_host, host)
    except socket.gaierror as exc:
        raise httpx.ConnectError(f"Domain not found: {exc}") from exc
    if not public:
        raise _Blocked(host)


def _dns_failure(exc: Exception) -> bool:
    text = str(exc).lower()
    return "domain not found" in text or "name or service not known" in text or "nodename nor servname" in text or "getaddrinfo failed" in text or "no address associated" in text


async def _request(client: httpx.AsyncClient, url: str) -> tuple[int, str]:
    """Final status code and URL after following redirects safely."""
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        parts = urlsplit(current)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise _Blocked(current)
        await _resolve_public(parts.hostname)
        response = await client.head(current)
        if response.status_code in (400, 403, 405, 406, 429, 501) or response.status_code >= 500:
            # Plenty of servers answer HEAD badly; ask for the page itself.
            async with client.stream("GET", current) as streamed:
                response = streamed
        if response.is_redirect and response.headers.get("location"):
            current = urljoin(current, response.headers["location"])
            continue
        return response.status_code, current
    return 310, current  # redirect loop


def _verdict(code: int) -> tuple[str, str]:
    if 200 <= code < 300:
        return "working", "The page opens."
    if code in (404, 410):
        return "broken", "The page no longer exists." if code == 404 else "The page has been removed."
    if code in (401, 403, 429, 451):
        return "unconfirmed", "The site blocks automatic checks. Open it to see if it works."
    if code == 310:
        return "unconfirmed", "The link keeps redirecting. Open it to check."
    if code >= 500:
        return "unconfirmed", "The site had a server error. It may be down for now."
    return "unconfirmed", f"The site answered with an unusual code ({code}). Open it to check."


_CANARY_HOSTS = ("www.google.com", "doi.org", "www.wikipedia.org")


def _dns_works() -> bool:
    """Whether this machine can look up ordinary websites at all.

    Without it, a missing domain would be confused with no internet (or a
    network that only allows some sites), and every link would read as dead.
    """
    for host in _CANARY_HOSTS:
        try:
            socket.getaddrinfo(host, 443)
            return True
        except OSError:
            continue
    return False


async def _check_one(client: httpx.AsyncClient, link: dict[str, Any], dns_ok: bool = True) -> dict[str, Any]:
    url = link["url"]
    try:
        code, final_url = await _request(client, url)
    except _Blocked:
        return {**link, "status": "skipped", "code": None, "note": "Not a public web address, so it wasn't opened."}
    except httpx.TimeoutException:
        return {**link, "status": "unconfirmed", "code": None, "note": "The site didn't answer in time."}
    except httpx.HTTPError as exc:
        if _dns_failure(exc):
            if dns_ok:
                return {**link, "status": "broken", "code": None, "note": "The website's domain no longer exists."}
            return {**link, "status": "unconfirmed", "code": None, "note": "We couldn't look up this site from the server."}
        return {**link, "status": "unconfirmed", "code": None, "note": "We couldn't connect to the site."}
    status, note = _verdict(code)
    moved = final_url.rstrip("/") != url.rstrip("/") and status == "working"
    return {**link, "status": status, "code": code, "note": note, "final_url": final_url if moved else None}


async def check_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(8)
    dns_ok = await asyncio.to_thread(_dns_works)
    # trust_env keeps any proxy the machine needs; redirects are followed by hand.
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=False) as client:
        async def run(link: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                try:
                    return await _check_one(client, link, dns_ok)
                except Exception as exc:  # one odd link must not sink the report
                    logger.warning("Link check failed for %s: %s", link.get("url"), exc)
                    return {**link, "status": "unconfirmed", "code": None, "note": "We couldn't check this link."}

        return list(await asyncio.gather(*(run(link) for link in links)))
