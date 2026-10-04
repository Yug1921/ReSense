import hashlib
import io
import re
from dataclasses import dataclass, field

import pdfplumber
from docx import Document

_HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?|[IVX]+\.)?\s*"
    r"([A-Z][A-Za-z0-9 ,\-:]{2,80})\s*$"
)
_COMMON_SECTION_NAMES = {
    "abstract", "introduction", "background", "related work", "methodology",
    "method", "methods", "materials and methods", "experiments", "results",
    "discussion", "conclusion", "conclusions", "future work", "references",
    "acknowledgments", "acknowledgements", "limitations", "definitions",
    "evaluation", "datasets", "analysis",
}
_TABLE_CAPTION_RE = re.compile(
    r"^\s*table\s+\d+[a-z]?\b.*$", re.IGNORECASE
)


@dataclass
class ParsedPaper:
    raw_text: str
    structure: dict = field(default_factory=dict)
    status: str = "ready"


class UnsupportedFileTypeError(Exception):
    pass


class FileParsingError(Exception):
    pass


def compute_file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def extract_text_and_tables_from_pdf(file_bytes: bytes) -> tuple[str, list[dict]]:
    """
    Extracts both the plain text AND any real (structured, multi-row,
    multi-column) tables from the PDF, in one pass over the same
    pdfplumber document.

    Tables are extracted via pdfplumber's own layout-based table detector
    (extract_tables) rather than asked from the LLM based on prose text —
    this is what actually lets us tell a real table apart from a figure,
    since tables are a genuine structured-grid layout on the page, not
    just "an image that looks tabular."
    """
    try:
        text_parts: list[str] = []
        tables: list[dict] = []

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page_index, page in enumerate(pdf.pages):
                text_parts.append(page.extract_text() or "")

                page_tables: list[dict] = []
                for raw_table in page.extract_tables():
                    cleaned_rows = [
                        [(cell or "").strip() for cell in row]
                        for row in raw_table
                        if any((cell or "").strip() for cell in row)
                    ]
                    # pdfplumber occasionally mis-detects a paragraph of
                    # body text as a fake 1-column "table" — a real table
                    # needs at least 2 rows and 2 columns to count.
                    if len(cleaned_rows) < 2 or len(cleaned_rows[0]) < 2:
                        continue

                    header, *body_rows = cleaned_rows
                    lines = [
                        " | ".join(header),
                        " | ".join("---" for _ in header),
                    ]
                    lines.extend(" | ".join(row) for row in body_rows)

                    page_tables.append(
                        {
                            "page_number": page_index + 1,
                            "content": "\n".join(lines),
                        }
                    )

                # Borderless tables and tables mixed with charts are commonly
                # missed by extract_tables(). Keep the caption and nearby text
                # as a useful fallback instead of reporting no table at all.
                if not page_tables:
                    page_lines = [line.strip() for line in (page.extract_text() or "").splitlines()]
                    for line_index, line in enumerate(page_lines):
                        if not _TABLE_CAPTION_RE.match(line):
                            continue
                        table_lines = [line]
                        for candidate in page_lines[line_index + 1 : line_index + 31]:
                            if _TABLE_CAPTION_RE.match(candidate) or re.match(
                                r"^\s*(?:figure|fig\.?\s*\d+)", candidate, re.IGNORECASE
                            ):
                                break
                            if candidate:
                                table_lines.append(candidate)
                        if len(table_lines) > 1:
                            tables.append(
                                {
                                    "page_number": page_index + 1,
                                    "content": "\n".join(table_lines),
                                }
                            )

                tables.extend(page_tables)

        return "\n".join(text_parts).strip(), tables
    except Exception as exc:
        raise FileParsingError(f"Could not read PDF: {exc}") from exc


def extract_text_from_docx(file_bytes: bytes) -> str:
    try:
        doc = Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs).strip()
    except Exception as exc:
        raise FileParsingError(f"Could not read DOCX: {exc}") from exc


def detect_structure(raw_text: str) -> dict:
    lines = raw_text.splitlines()
    sections: dict[str, list[str]] = {}
    current_section = "preamble"
    sections[current_section] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        match = _HEADING_RE.match(stripped)
        normalized_heading = re.sub(
            r"^\s*(?:\d+(?:\.\d+)*|[IVX]+)[\s.)-]+", "", stripped, flags=re.IGNORECASE
        ).strip(" .:").lower()
        looks_like_heading = bool(match) and (
            normalized_heading in _COMMON_SECTION_NAMES
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
    lower = filename.lower()
    tables: list[dict] = []

    if lower.endswith(".pdf"):
        raw_text, tables = extract_text_and_tables_from_pdf(file_bytes)
    elif lower.endswith(".docx") or lower.endswith(".doc"):
        raw_text = extract_text_from_docx(file_bytes)
    else:
        raise UnsupportedFileTypeError(
            f"Unsupported file type for '{filename}'. Only PDF and DOCX are accepted."
        )

    if not raw_text or len(raw_text.split()) < 20:
        return ParsedPaper(raw_text=raw_text, structure={}, status="empty_text")

    structure = detect_structure(raw_text)
    structure["tables"] = tables
    return ParsedPaper(raw_text=raw_text, structure=structure, status="ready")