"""
Track D — basic visualization/analysis.

Section-length and keyword-frequency are pure computation (no LLM call,
no cost, instant). Only the paper-type/complexity classification uses
one small LLM call — and that result gets cached just like summaries,
so re-viewing the analysis tab is always free after the first load.
"""
import json
import re
import unicodedata
from collections import Counter

from app.services.llm import call_openrouter, LLMRequestError
from app.services.prompts import build_classification_prompt

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for",
    "with", "as", "by", "is", "are", "was", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "at", "from", "we",
    "our", "their", "which", "can", "have", "has", "had", "not", "also",
    "such", "than", "then", "into", "when", "while", "using", "used",
    "use", "based", "between", "over", "each", "more", "most", "other",
    "may", "will", "would", "could", "should", "one", "two", "three",
    "figure", "table", "et", "al", "i.e", "e.g",
    # Layout and reference words that say nothing about the topic
    "fig", "figs", "figures", "tables", "eq", "eqn", "eqs", "sec", "section", "sections",
    "ref", "refs", "arxiv", "preprint", "proceedings", "conference", "pages", "vol",
    # More function words
    "where", "thus", "however", "both", "all", "any", "only", "here", "there", "about",
    "after", "before", "through", "under", "without", "within", "because", "since",
    "does", "nor", "out", "very", "just", "how", "what", "who", "whom", "why", "you",
    "your", "his", "her", "him", "them", "they", "she", "some", "many", "much", "such",
    "first", "second", "same", "different", "also", "into", "onto", "upon", "per",
    "while", "whereas", "often", "further", "show", "shows", "shown", "see", "use",
    "uses", "given", "make", "makes", "made", "well", "less", "least", "like",
}
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-]{2,}")
_SECTION_GROUPS = {
    "abstract": ("abstract",),
    "introduction": ("introduction", "overview", "motivation"),
    "background": ("background", "related work", "literature review"),
    "method": ("method", "methodology", "approach", "materials"),
    "results": ("result", "evaluation", "experiment", "findings"),
    "discussion": ("discussion", "analysis"),
    "conclusion": ("conclusion", "summary", "future work"),
}
_COMPLEXITY_BANDS = ((2, "low"), (4, "medium-low"), (6, "medium"), (8, "high"), (10, "very high"))
_COMPLEXITY_TERMS = {
    "algorithm", "architecture", "dataset", "evaluation", "experiment",
    "equation", "parameter", "precision", "recall", "model", "methodology",
    "benchmark", "baseline", "classifier", "regression", "embedding",
}


def _clean_section_label(label: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", label).strip(" .:-")
    if not cleaned or re.fullmatch(r"[ivxlcdm]+", cleaned, re.IGNORECASE):
        return None
    if len(re.findall(r"[A-Za-z]", cleaned)) < 3:
        return None
    if cleaned.lower() == "preamble":
        return "Opening context"
    return cleaned


_TOP_HEADING_RE = re.compile(r"^(\d{1,2})\.?\s+([A-Z][^\n]{1,70})$")
_NAMED_HEADING_RE = re.compile(
    r"^(abstract|references|bibliography|acknowledge?ments?|conclusions?|appendix(?:es)?)\b[\s.:]*",
    re.IGNORECASE,
)


def _is_heading_title(title: str) -> bool:
    """A numbered line is a heading only if it reads like a title, not a sentence or footnote."""
    words = title.split()
    return 0 < len(words) <= 7 and not title.endswith(("-", ".", ",", ";")) and not re.search(r"\d{3,}", title)


def _sections_from_text(raw_text: str) -> list[dict]:
    """
    Split the paper at its top-level headings: "1 Introduction", "2. Related Work", ...
    plus Abstract, References, Acknowledgments and Appendix. Numbered headings must
    count up one at a time, which skips table rows, footnotes and subsections
    ("4.1 GLUE" stays inside "4 Experiments").
    """
    sections: list[dict] = []
    current: dict | None = None
    last_number = 0
    in_back_matter = False

    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        label = None
        numbered = _TOP_HEADING_RE.match(stripped)
        named = _NAMED_HEADING_RE.match(stripped)
        if numbered and not in_back_matter:
            number, title = int(numbered.group(1)), numbered.group(2).strip()
            if number == last_number + 1 and _is_heading_title(title):
                label, last_number = title, number
        elif named and len(stripped.split()) <= 6:
            name = named.group(1).lower()
            if name.startswith("appendix"):
                if not any(s["label"] == "Appendix" for s in sections):
                    label, in_back_matter = "Appendix", True
            elif name in ("references", "bibliography"):
                if not any(s["label"] == "References" for s in sections):
                    label = "References"
            elif not any(s["label"].lower() == name for s in sections):
                label = stripped.rstrip(" .:")
                label = label[0].upper() + label[1:].lower()

        if label:
            current = {"label": label, "value": 0}
            sections.append(current)
            continue
        if current is not None:
            current["value"] += len(stripped.split())

    return [s for s in sections if s["value"] > 0]


def section_length_stats(structure: dict | None, raw_text: str = "") -> list[dict]:
    """Words per top-level section, in reading order."""
    stats = _sections_from_text(raw_text) if raw_text else []
    if len(stats) >= 2:
        return stats

    # Fallback: the parser's detected sections, minus labels that are clearly
    # not headings (numbers, model names such as "VGG-16", the title block).
    sections = (structure or {}).get("sections") or {}
    fallback = []
    for name, text in sections.items():
        label = _clean_section_label(name)
        if not label or label == "Opening context" or re.search(r"\d", label):
            continue
        words = len(text.split())
        if words >= 30:
            fallback.append({"label": label, "value": words})
    return fallback


def structure_score(section_lengths: list[dict]) -> int:
    """Score recognizable research-paper organization from 0 to 100."""
    labels = [item["label"].lower() for item in section_lengths]
    groups_found = {
        group
        for group, aliases in _SECTION_GROUPS.items()
        if any(alias in label for alias in aliases for label in labels)
    }
    if not labels:
        return 0
    coverage = len(groups_found) / len(_SECTION_GROUPS)
    section_count_score = min(1.0, len(labels) / 6) * 0.2
    return min(100, round((coverage * 0.8 + section_count_score) * 100))


def deterministic_complexity_score(raw_text: str, section_lengths: list[dict]) -> int:
    """Estimate reading difficulty from length, structure, and technical density."""
    words = raw_text.split()
    word_count = len(words)
    lower_text = raw_text.lower()
    score = 2
    if word_count >= 5000:
        score += 2
    if word_count >= 12000:
        score += 1
    if len(section_lengths) >= 5:
        score += 1
    technical_hits = sum(lower_text.count(term) for term in _COMPLEXITY_TERMS)
    if technical_hits >= 20:
        score += 1
    if technical_hits >= 60:
        score += 1
    average_word_length = sum(len(word.strip(".,;:()[]")) for word in words) / max(1, word_count)
    if average_word_length >= 6.2:
        score += 1
    return max(1, min(10, score))


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def keyword_frequency(raw_text: str, top_n: int = 15) -> list[dict]:
    """
    Most-used topic words. Singular and plural count together ("layer" + "layers"),
    trailing hyphens from names like "ResNet-50" are dropped, and each term is
    shown in the spelling the paper uses most ("ImageNet", not "imagenet").
    """
    counts: Counter = Counter()
    spellings: dict[str, Counter] = {}
    # NFKC turns PDF ligatures back into letters ("ﬁne-tuning" -> "fine-tuning").
    for match in _WORD_RE.findall(unicodedata.normalize("NFKC", raw_text)):
        surface = match.strip("-")
        word = surface.lower()
        if len(word) < 3 or word in _STOPWORDS or "-" in word and len(word.replace("-", "")) < 3:
            continue
        key = _singular(word)
        if key in _STOPWORDS:
            continue
        counts[key] += 1
        spellings.setdefault(key, Counter())[surface] += 1

    result = []
    for key, count in counts.most_common(top_n):
        forms = spellings[key]
        # Prefer the most used form; break ties toward a capitalised proper name.
        label = max(forms.items(), key=lambda item: (item[1], item[0] != item[0].lower()))[0]
        if label.isupper() and len(label) > 4:
            label = label.lower()  # headings in capitals, not acronyms
        result.append({"label": label, "value": count})
    return result


async def classify_paper(raw_text: str) -> dict | None:
    """Returns None (rather than raising) on ANY failure here — network blips, OpenRouter errors, malformed JSON, whatever. Classification is a nice-to-have; the two computed charts (section lengths, keywords) must never be taken down by it."""

    system_prompt, user_prompt = build_classification_prompt(raw_text)
    try:
        raw_response = await call_openrouter(system_prompt, user_prompt, max_tokens=350, temperature=0.1)

    except Exception:
        return None

    except LLMRequestError:
        return None

    match = re.search(r"\{[^{}]*\}", raw_response, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        score = max(1, min(10, int(parsed.get("complexity_score", 5))))
        complexity = next(label for ceiling, label in _COMPLEXITY_BANDS if score <= ceiling)
        return {
            "paper_type": parsed.get("paper_type", "other"),
            "complexity": complexity,
            "complexity_score": score,
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
