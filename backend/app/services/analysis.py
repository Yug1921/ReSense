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

from app.services.llm import call_openrouter
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


def section_length_stats(structure: dict | None) -> list[dict]:
    sections = (structure or {}).get("sections") or {}
    stats = [
        {"label": name, "value": len(text.split())}
        for name, text in sections.items()
        if text.strip()
    ]
    # Biggest sections first — makes for a more readable bar chart.
    return sorted(stats, key=lambda s: s["value"], reverse=True)


def keyword_frequency(raw_text: str, top_n: int = 15) -> list[dict]:
    words = [w.lower() for w in _WORD_RE.findall(raw_text)]
    words = [w for w in words if w not in _STOPWORDS]
    counts = Counter(words).most_common(top_n)
    return [{"label": word, "value": count} for word, count in counts]


async def classify_paper(raw_text: str) -> dict | None:
    """Returns None (rather than raising) on ANY failure here — network blips, OpenRouter errors, malformed JSON, whatever. Classification is a nice-to-have; the two computed charts (section lengths, keywords) must never be taken down by it."""

    system_prompt, user_prompt = build_classification_prompt(raw_text)
    try:
        raw_response = await call_openrouter(system_prompt, user_prompt, max_tokens=100, temperature=0.1)
    except LLMRequestError:
        return None

    cleaned = raw_response.strip().strip("`")
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()
    try:
        parsed = json.loads(cleaned)
        return {
            "paper_type": parsed.get("paper_type", "other"),
            "complexity": parsed.get("complexity", "medium"),
            "complexity_score": int(parsed.get("complexity_score", 5)),
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
