"""
Track A — File ingestion & parsing.

Extracts plain text and a rough section structure from an uploaded
PDF or DOCX. This is the ONLY place in the app that touches the raw
file — every other feature (summarize, analyze, ask) reads the
cached `raw_text` / `structure_json` produced here instead of
re-parsing the file.
"""
import hashlib
import re
from dataclasses import dataclass, field

import pdfplumber
from docx import Document

# A heading looks like a short, title-cased or all-caps line, optionally
# numbered ("3.", "3.1", "III."), with no trailing punctuation like a period
# mid-sentence. This is intentionally simple — "rough structure", not a
# full document-layout model.
_HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?|[IVX]+\.)?\s*"
    r"([A-Z][A-Za-z0-9 ,\-:]{2,80})\s*$"
)
_COMMON_SECTION_NAMES = {
    "abstract", "introduction", "background", "related work", "methodology",
    "method", "methods", "materials and methods", "experiments", "results",
    "discussion", "conclusion", "conclusions", "future work", "references",
    "acknowledgments", "acknowledgements", "limitations",
}


@dataclass
class ParsedPaper:
    raw_text: str
    structure: dict = field(default_factory=dict)
    status: str = "ready"  # ready | parse_failed | empty_text


class UnsupportedFileTypeError(Exception):
    pass


class FileParsingError(Exception):
    pass


def compute_file_hash(file_bytes: bytes) -> str:
    """Used to dedupe repeat uploads of the same file (see Track A checklist)."""
    return hashlib.sha256(file_bytes).hexdigest()


def extract_text_from_pdf(file_bytes: bytes) -> str:
    import io
    try:
        text_parts = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
        return "\n".join(text_parts).strip()
    except Exception as exc:  # corrupted / unreadable PDF
        raise FileParsingError(f"Could not read PDF: {exc}") from exc


def extract_text_from_docx(file_bytes: bytes) -> str:
    import io
    try:
        doc = Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs).strip()
    except Exception as exc:
        raise FileParsingError(f"Could not read DOCX: {exc}") from exc


def detect_structure(raw_text: str) -> dict:
    """
    Very lightweight structure detection: scans line-by-line for
    heading-shaped lines (especially ones matching common paper section
    names) and buckets the text under them. Good enough for Track D's
    "section length breakdown" chart and for giving Track C something
    to chunk on later — not a substitute for real layout parsing.
    """
    lines = raw_text.splitlines()
    sections: dict[str, list[str]] = {}
    current_section = "preamble"
    sections[current_section] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        match = _HEADING_RE.match(stripped)
        looks_like_heading = bool(match) and (
            stripped.lower().strip(" .:0123456789ivx") in _COMMON_SECTION_NAMES
            or (len(stripped) < 60 and stripped.isupper())
        )
        if looks_like_heading:
            current_section = stripped
            sections.setdefault(current_section, [])
        else:
            sections[current_section].append(stripped)

    return {
        "sections": {name: "\n".join(content) for name, content in sections.items()},
        "section_order": list(sections.keys()),
        "word_count": len(raw_text.split()),
    }


def parse_file(filename: str, file_bytes: bytes) -> ParsedPaper:
    """Top-level entry point used by the /upload route."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        raw_text = extract_text_from_pdf(file_bytes)
    elif lower.endswith(".docx") or lower.endswith(".doc"):
        raw_text = extract_text_from_docx(file_bytes)
    else:
        raise UnsupportedFileTypeError(
            f"Unsupported file type for '{filename}'. Only PDF and DOCX are accepted."
        )

    if not raw_text or len(raw_text.split()) < 20:
        # Handles the "scanned/image-only PDF, no extractable text" case
        # from the reliability checklist explicitly, rather than silently
        # returning an empty summary later.
        return ParsedPaper(raw_text=raw_text, structure={}, status="empty_text")

    structure = detect_structure(raw_text)
    return ParsedPaper(raw_text=raw_text, structure=structure, status="ready")
