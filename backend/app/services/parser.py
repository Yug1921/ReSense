import hashlib
import io
import importlib
import re
import unicodedata
from dataclasses import dataclass, field

import pdfplumber
from docx import Document

try:
    fitz = importlib.import_module("pymupdf")
except ImportError:
    fitz = None

_HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?|[IVX]+\.)?\s*"
    r"([A-Z][A-Za-z0-9 ,\-:]{2,80})\s*$"
)
_COMMON_SECTION_NAMES = {
    "abstract", "introduction", "background", "related work", "methodology",
    "method", "methods", "materials and methods", "experiments", "results",
    "discussion", "conclusion", "conclusions", "future work", "references",
    "acknowledgments", "acknowledgements", "limitations", "definitions",
    "evaluation", "datasets", "analysis", "bibliography", "works cited",
    "literature cited",
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
            coordinate_pdf = fitz.open(stream=file_bytes, filetype="pdf") if fitz else None
            for page_index, page in enumerate(pdf.pages):
                if coordinate_pdf is not None:
                    text_parts.append(_extract_page_text_in_reading_order(coordinate_pdf[page_index]))
                else:
                    text_parts.append(page.extract_text() or "")

                page_tables: list[dict] = []
                for raw_table in page.extract_tables():
                    cleaned_rows = [
                        [(cell or "").strip() for cell in row]
                        for row in raw_table
                        if any((cell or "").strip() for cell in row)
                    ]
                    # pdfplumber occasionally mis-detects a paragraph of
                    # body text as a misdetected 1-column "table" — a real table
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
            if coordinate_pdf is not None:
                coordinate_pdf.close()

        return "\n".join(_remove_repeated_edge_lines(text_parts)).strip(), tables
    except Exception as exc:
        raise FileParsingError(f"Could not read PDF: {exc}") from exc


def _extract_page_text_in_reading_order(page: object) -> str:
    """Rebuild page text using per-page geometry and normal column order."""
    lines = _extract_coordinate_lines(page)
    if not lines:
        return ""

    page_width = page.rect.width  # type: ignore[attr-defined]
    page_height = getattr(page.rect, "height", None)  # type: ignore[attr-defined]
    if page_height is None:
        page_height = page.rect.y1 if hasattr(page.rect, "y1") else 800  # type: ignore[attr-defined]
    lines = [
        line
        for line in lines
        if not _is_centered_page_footer(line, page_width, page_height)
    ]
    if not lines:
        return ""

    split = _detect_column_split(lines, page_width)
    if split is None:
        lines = _merge_line_fragments(lines)
        return "\n".join(line[4] for line in sorted(lines, key=lambda item: (item[1], item[0])))

    lines = _merge_line_fragments(lines, split)
    column_lines = [line for line in lines if line[2] - line[0] < page_width * 0.78]
    left = [line for line in column_lines if (line[0] + line[2]) / 2 < split]
    right = [line for line in column_lines if (line[0] + line[2]) / 2 >= split]
    full_width = [line for line in lines if line not in column_lines]
    ordered = sorted(full_width, key=lambda item: (item[1], item[0]))
    if left and right:
        first_column_y = min(line[1] for line in left + right)
        last_column_y = max(line[3] for line in left + right)
        before = [line for line in ordered if line[3] <= first_column_y]
        after = [line for line in ordered if line[1] >= last_column_y]
        middle = [line for line in ordered if line not in before and line not in after]
        ordered_lines = (
            sorted(before, key=lambda item: (item[1], item[0]))
            + sorted(left, key=lambda item: (item[1], item[0]))
            + sorted(right, key=lambda item: (item[1], item[0]))
            + sorted(middle, key=lambda item: (item[1], item[0]))
            + sorted(after, key=lambda item: (item[1], item[0]))
        )
        return "\n".join(line[4] for line in ordered_lines)
    return "\n".join(line[4] for line in sorted(lines, key=lambda item: (item[1], item[0])))


def _merge_line_fragments(
    lines: list[tuple[float, float, float, float, str]],
    split: float | None = None,
) -> list[tuple[float, float, float, float, str]]:
    """Merge same-column fragments that PyMuPDF reports as separate lines."""
    rows: list[list[tuple[float, float, float, float, str]]] = []
    for line in sorted(lines, key=lambda item: (item[1], item[0])):
        if rows and abs(rows[-1][0][1] - line[1]) <= 1.5:
            rows[-1].append(line)
        else:
            rows.append([line])

    merged: list[tuple[float, float, float, float, str]] = []
    for row in rows:
        for line in sorted(row, key=lambda item: item[0]):
            if not merged or abs(merged[-1][1] - line[1]) > 1.5:
                merged.append(line)
                continue
            previous = merged[-1]
            same_region = split is None or (
                ((previous[0] + previous[2]) / 2 < split)
                == ((line[0] + line[2]) / 2 < split)
            )
            close_horizontally = 0 <= line[0] - previous[2] <= 14
            if same_region and close_horizontally:
                merged[-1] = (
                    previous[0],
                    min(previous[1], line[1]),
                    line[2],
                    max(previous[3], line[3]),
                    f"{previous[4]} {line[4]}",
                )
            else:
                merged.append(line)
    return merged


def _join_spans(spans: list[dict]) -> str:
    """Join a line's spans, adding a space only where the PDF leaves a gap.

    Kerned headings arrive as many small spans ("S" "ummar" "y"); joining
    every span with a space would print "S ummar y".
    """
    text = ""
    previous_end = None
    for span in spans:
        piece = str(span.get("text", ""))
        if not piece.strip():
            if text and not text.endswith(" "):
                text += " "
            previous_end = None
            continue
        bbox = span.get("bbox")
        size = float(span.get("size") or 10)
        if text and not text.endswith(" ") and not piece.startswith(" "):
            gap = (bbox[0] - previous_end) if bbox and previous_end is not None else size
            if gap > size * 0.15:
                text += " "
        text += piece
        previous_end = bbox[2] if bbox else None
    return text.strip()


def _extract_coordinate_lines(page: object) -> list[tuple[float, float, float, float, str]]:
    """Return non-empty PDF text lines as (x0, y0, x1, y1, text)."""
    try:
        blocks = page.get_text("dict")["blocks"]  # type: ignore[attr-defined]
        lines = []
        for block in blocks:
            for line in block.get("lines", []):
                text = _join_spans(line.get("spans", []))
                text = re.sub(r"\s+", " ", text)
                if text:
                    x0, y0, x1, y1 = line["bbox"]
                    lines.append((float(x0), float(y0), float(x1), float(y1), text))
        if lines:
            return lines
    except (AttributeError, KeyError, TypeError):
        pass

    words = page.get_text("words")  # type: ignore[attr-defined]
    grouped: list[list[tuple[float, float, float, float, str]]] = []
    for word in sorted(words or [], key=lambda item: (item[1], item[0])):
        x0, y0, x1, y1, text = word[:5]
        for current in grouped:
            if abs(current[0][1] - y0) <= 3:
                current.append((x0, y0, x1, y1, str(text)))
                break
        else:
            grouped.append([(x0, y0, x1, y1, str(text))])
    return [
        (
            min(word[0] for word in line),
            min(word[1] for word in line),
            max(word[2] for word in line),
            max(word[3] for word in line),
            " ".join(word[4] for word in sorted(line, key=lambda item: item[0])),
        )
        for line in grouped
    ]


def _detect_column_split(
    lines: list[tuple[float, float, float, float, str]], page_width: float
) -> float | None:
    """Find the whitespace gap nearest the page center between two columns."""
    column_lines = [
        line for line in lines if line[2] - line[0] < page_width * 0.78
    ]
    if len(column_lines) < 6:
        return None

    page_center = page_width / 2
    edge_candidates = sorted(
        {
            round(edge, 1)
            for line in column_lines
            for edge in (line[0], line[2])
        }
    )
    candidates: list[tuple[float, float]] = []
    for left_edge, right_edge in zip(edge_candidates, edge_candidates[1:]):
        gap = right_edge - left_edge
        if gap < 8:
            continue
        split = (left_edge + right_edge) / 2
        left_count = sum(
            (line[0] + line[2]) / 2 < split for line in column_lines
        )
        right_count = sum(
            (line[0] + line[2]) / 2 >= split for line in column_lines
        )
        if left_count >= 3 and right_count >= 3:
            candidates.append((abs(split - page_center), split))

    if not candidates:
        return None
    return min(candidates)[1]


def _is_centered_page_footer(
    line: tuple[float, float, float, float, str],
    page_width: float,
    page_height: float,
) -> bool:
    """Exclude centered page-number/footer blocks using geometry, not digits."""
    x0, y0, x1, y1, _ = line
    line_center = (x0 + x1) / 2
    return (
        y0 >= page_height * 0.9
        and abs(line_center - page_width / 2) <= page_width * 0.12
        and x1 - x0 <= page_width * 0.16
    )


def _remove_repeated_edge_lines(page_texts: list[str]) -> list[str]:
    """Remove exact repeated running headers/footers without dropping body text."""
    edge_counts: dict[str, int] = {}
    for text in page_texts:
        edge_lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in edge_lines[:2] + edge_lines[-2:]:
            if len(line) <= 120:
                edge_counts[line] = edge_counts.get(line, 0) + 1
    repeated = {line for line, count in edge_counts.items() if count >= 2}
    if not repeated:
        return page_texts
    return [
        "\n".join(line for line in text.splitlines() if line.strip() not in repeated)
        for text in page_texts
    ]


def extract_text_from_docx(file_bytes: bytes) -> str:
    try:
        doc = Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs).strip()
    except Exception as exc:
        raise FileParsingError(f"Could not read DOCX: {exc}") from exc


_NUMBERED_HEADING_RE = re.compile(
    r"^(?P<num>\d{1,2}(?:\.\d{1,2}){0,2}|[IVX]{1,5}|[A-H])\.?\s+(?P<title>[A-Z][^\n]{1,80})$"
)
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8,
          "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15}
# Words a heading can't end on; such a line is the start of a sentence or footnote.
_DANGLING_END_RE = re.compile(r"(?:,|\b(?:a|an|the|of|in|on|and|or|to|for|with|by|but|also|may|is|are|was|were|be))$", re.IGNORECASE)


def _plain_heading(stripped: str) -> str:
    return re.sub(r"^\s*(?:\d+(?:\.\d+)*|[IVX]+|[A-H])[\s.)-]+", "", stripped, flags=re.IGNORECASE).strip(" .:").lower()


def _heading_title_ok(title: str) -> bool:
    words = title.split()
    return (
        1 <= len(words) <= 12
        and not _DANGLING_END_RE.search(title)
        and not title.rstrip().endswith((".", "-"))
        and sum(ch.isalpha() for ch in title) >= 3
    )


def detect_structure(raw_text: str) -> dict:
    """Split the paper into its top-level sections, in reading order.

    A line counts as a heading only when it reads like one: a well-known
    section name ("Abstract", "References"), or a numbered heading whose
    number continues the paper's own sequence (1, 2, 3 or I, II, III, and
    appendix letters A, B, C after the references). Short capitalised lines
    such as table cells ("MRR", "E 150") and numbered footnotes
    ("16 Recommendation frameworks such as ...") are body text.
    Subsection headings (4.1, 4.2) stay inside their section but are listed
    in "outline" so questions about the paper's structure can be answered.
    """
    sections: dict[str, list[str]] = {"preamble": []}
    outline: list[str] = []
    current = "preamble"
    last_top = 0
    last_letter = ""
    sub_seen: set[str] = set()
    dotted: bool | None = None  # "1. Intro" vs "1 Intro": a paper sticks to one
    in_references = False

    def start(name: str) -> None:
        nonlocal current
        name = name if name not in sections else f"{name} ({len(sections)})"
        current = name
        sections[name] = []
        outline.append(name)

    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        plain = _plain_heading(stripped)
        match = _NUMBERED_HEADING_RE.match(stripped)

        if plain in _COMMON_SECTION_NAMES and len(stripped) <= 60 and stripped[0].isupper() and (
            match or stripped.lower().strip(" .:") == plain
        ):
            if match and match.group("num").isdigit():
                last_top = int(match.group("num"))
            in_references = in_references or plain in {"references", "bibliography", "works cited", "literature cited"}
            start(stripped)
            continue

        if match and _heading_title_ok(match.group("title")):
            num = match.group("num")
            has_dot = stripped[len(num)] == "."
            if in_references and "." not in num and not num.isalpha():
                pass  # numbered entries of the reference list
            elif num.isdigit() or num in _ROMAN and num != "I" or num == "I" and last_top == 0:
                value = int(num) if num.isdigit() else _ROMAN[num]
                if value == last_top + 1 and value <= 30 and dotted in (None, has_dot):
                    dotted = has_dot
                    last_top = value
                    start(stripped)
                    continue
            elif "." in num:
                top, rest = num.split(".", 1)
                if int(top) == last_top and num not in sub_seen:
                    sub_seen.add(num)
                    outline.append(f"  {stripped}")
            elif len(num) == 1 and num.isalpha() and last_top and len(match.group("title").split()) >= 2:
                expected = chr(ord(last_letter) + 1) if last_letter else "A"
                if num == expected and any("reference" in s.lower() or "bibliograph" in s.lower() for s in sections):
                    last_letter = num
                    start(stripped)
                    continue
        sections[current].append(stripped)

    return {
        "sections": {name: "\n".join(content) for name, content in sections.items()},
        "section_order": list(sections.keys()),
        "outline": outline,
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

    # Ligatures ("ﬁ") and other presentation forms would stop "filtering"
    # matching "ﬁltering" in search and headings.
    raw_text = unicodedata.normalize("NFKC", raw_text or "")
    if not raw_text or len(raw_text.split()) < 20:
        return ParsedPaper(raw_text=raw_text, structure={}, status="empty_text")

    structure = detect_structure(raw_text)
    structure["tables"] = tables
    return ParsedPaper(raw_text=raw_text, structure=structure, status="ready")