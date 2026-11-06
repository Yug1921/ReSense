"""
Split a paper into short passages for /ask to search.

Sections come from the parser's heading rules applied to the text itself,
so papers saved before those rules improved get clean labels too. Each
passage is labelled with its section and, where there is one, its
subsection ("4 Survey of the evaluations › 4.3 Coverage"), and passages
overlap a little so a sentence cut at a boundary still appears whole once.
"""
import re

from app.services.parser import detect_structure

_TARGET_WORDS_PER_CHUNK = 180
_OVERLAP_WORDS = 30
_SUBSECTION_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){1,2})\.?\s+([A-Z].{1,80})$")


def _label(name: str) -> str:
    return "Opening page" if name == "preamble" else re.sub(r"\s\(\d+\)$", "", name)


def _windows(words: list[str]) -> list[str]:
    step = _TARGET_WORDS_PER_CHUNK - _OVERLAP_WORDS
    pieces = []
    for start in range(0, len(words), step):
        piece = words[start : start + _TARGET_WORDS_PER_CHUNK]
        if pieces and len(piece) <= _OVERLAP_WORDS:
            break  # already covered by the previous window's tail
        pieces.append(" ".join(piece))
    return pieces


def chunk_paper(raw_text: str, structure: dict | None, extra_chunks: list[dict] | None = None) -> list[dict]:
    """
    extra_chunks: additional {section, text} chunks to fold in on top of
    the paper's own text, e.g. captioned figures and extracted tables, so
    /ask can answer from them the same way it answers from the prose.
    """
    detected = detect_structure(raw_text) if raw_text else structure or {}
    sections = detected.get("sections") or {}
    outline = set(detected.get("outline") or [])
    chunks: list[dict] = []

    for name, text in sections.items():
        section = _label(name)
        # Group the section's lines under its subsection headings.
        groups: list[tuple[str, list[str]]] = [(section, [])]
        for line in text.splitlines():
            stripped = line.strip()
            if f"  {stripped}" in outline and _SUBSECTION_RE.match(stripped):
                groups.append((f"{section} › {stripped}", []))
            else:
                groups[-1][1].extend(stripped.split())
        for label, words in groups:
            for piece in _windows(words):
                chunks.append({"section": label, "text": piece})

    if not chunks and raw_text.strip():
        chunks.append({"section": "paper", "text": raw_text})

    chunks.extend(extra_chunks or [])
    return chunks


def paper_outline(raw_text: str) -> list[str]:
    """The paper's headings in order, subsections indented."""
    return [
        "Opening page (title, authors, abstract)" if line == "preamble" else line
        for line in detect_structure(raw_text).get("outline", [])
    ]
