"""
Track D — basic visualization/analysis.

Section-length and keyword-frequency are pure computation (no LLM call,
no cost, instant). Only the paper-type/complexity classification uses
one small LLM call — and that result gets cached just like summaries,
so re-viewing the analysis tab is always free after the first load.
"""
import json
import re
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


def section_length_stats(structure: dict | None, raw_text: str = "") -> list[dict]:
    sections = (structure or {}).get("sections") or {}
    stats = []
    for name, text in sections.items():
        label = _clean_section_label(name)
        if label and text.strip():
            stats.append({"label": label, "value": len(text.split())})
    if len(stats) < 2 and raw_text:
        from app.services.parser import detect_structure

        inferred = detect_structure(raw_text)
        sections = inferred.get("sections") or {}
        stats = []
        for name, text in sections.items():
            label = _clean_section_label(name)
            if label and text.strip():
                stats.append({"label": label, "value": len(text.split())})
    # Biggest sections first — makes for a more readable bar chart.
    return sorted(stats, key=lambda s: s["value"], reverse=True)


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


def keyword_frequency(raw_text: str, top_n: int = 15) -> list[dict]:
    words = [w.lower() for w in _WORD_RE.findall(raw_text)]
    words = [w for w in words if w not in _STOPWORDS]
    counts = Counter(words).most_common(top_n)
    return [{"label": word, "value": count} for word, count in counts]


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
