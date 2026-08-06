"""
Track B — tone-conditioned prompt templates.

Three tones, three different *purposes*, not just three reading
levels:
  - simple:    understand what the paper says, in plain language
  - technical: evaluate the paper's rigor, method, and contribution
  - connect:   understand why it matters and where it applies

Each builds a (system_prompt, user_prompt) pair for `call_openrouter`.
"""

# Free-tier models have a limited effective context; keep the paper
# excerpt bounded rather than sending the entire raw text every time.
_MAX_PAPER_CHARS = 9000


def _trim_paper_text(raw_text: str) -> str:
    if len(raw_text) <= _MAX_PAPER_CHARS:
        return raw_text
    return raw_text[:_MAX_PAPER_CHARS] + "\n\n[...paper truncated for length...]"


_SYSTEM_PROMPTS = {
    "simple": (
        "You are explaining a research paper to a curious layperson with no "
        "background in the field. Use plain, everyday language and short "
        "sentences. If you must use a technical term, define it in the same "
        "sentence using an everyday comparison. Avoid jargon, avoid citation "
        "clutter, and never assume prior knowledge of the field."
    ),
    "technical": (
        "You are summarizing a research paper for a knowledgeable reader in "
        "the same field — a fellow researcher or graduate student. Preserve "
        "precise terminology, the methodology, key metrics/results, and any "
        "stated limitations. Do not oversimplify or drop nuance for the sake "
        "of brevity."
    ),
    "connect": (
        "You are summarizing a research paper for someone who is not a "
        "specialist but works in an adjacent field, is a student, or is "
        "practically minded — they want to know what this research means in "
        "the real world. Stay substantive and accurate, but foreground "
        "real-world relevance: relatable analogies, how the findings connect "
        "to everyday life, industry practice, or other fields, and concrete "
        "'so what can be done with this' takeaways. Do not drown the reader "
        "in jargon, but do not oversimplify into vagueness either — this is "
        "the bridge between a plain-language summary and a technical one."
    ),
}

_STRUCTURE_INSTRUCTION = (
    "Structure your response with these labeled parts, each 2-4 sentences "
    "unless noted:\n"
    "1. What it's about\n"
    "2. Why it matters\n"
    "3. Method in brief\n"
    "4. Key findings\n"
    "5. Limitations / caveats (1-2 sentences)"
)


def build_summary_prompt(tone: str, raw_text: str) -> tuple[str, str]:
    if tone not in _SYSTEM_PROMPTS:
        raise ValueError(f"Unknown tone: {tone}")

    system_prompt = f"{_SYSTEM_PROMPTS[tone]}\n\n{_STRUCTURE_INSTRUCTION}"
    paper_excerpt = _trim_paper_text(raw_text)
    user_prompt = (
        "Here is the extracted text of the research paper:\n\n"
        f"{paper_excerpt}\n\n"
        "Write the summary now, following the structure given."
    )
    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Track C — Q&A prompt
# ---------------------------------------------------------------------------

_ASK_SYSTEM_PROMPT = (
    "You are a precise research-paper assistant. You answer questions using "
    "ONLY the excerpts of the paper provided below — never your own outside "
    "knowledge. If the excerpts don't contain the answer, say plainly that "
    "the paper doesn't appear to cover that, rather than guessing. Be "
    "concise and accurate. When helpful, mention which section an answer "
    "came from (e.g. 'According to the Methodology section...')."
)


def build_ask_prompt(
    question: str, retrieved_chunks: list[dict], chat_history: list[dict]
) -> tuple[str, str]:
    """
    retrieved_chunks: [{"section": str, "text": str}, ...] from retrieval.py
    chat_history: [{"role": "user"|"assistant", "content": str}, ...] — most
    recent turns only (bounding this is what keeps the QA context window
    scoped to "one paper session", not the whole conversation ever).
    """
    context_blocks = "\n\n".join(
        f"[Excerpt from '{c['section']}']\n{c['text']}" for c in retrieved_chunks
    )

    history_text = ""
    if chat_history:
        history_lines = [f"{turn['role']}: {turn['content']}" for turn in chat_history]
        history_text = "Recent conversation so far:\n" + "\n".join(history_lines) + "\n\n"

    user_prompt = (
        f"Relevant excerpts from the paper:\n\n{context_blocks}\n\n"
        f"{history_text}"
        f"Question: {question}\n\n"
        "Answer using only the excerpts above."
    )
    return _ASK_SYSTEM_PROMPT, user_prompt


# ---------------------------------------------------------------------------
# Track D — classification prompt (paper type / complexity)
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM_PROMPT = (
    "You classify research papers. Respond with ONLY a compact JSON object, "
    "no prose, no markdown fences, in exactly this shape:\n"
    '{"paper_type": "empirical|theoretical|survey|case_study|other", '
    '"complexity": "low|medium|high", "complexity_score": <integer 1-10>}'
)


def build_classification_prompt(raw_text: str) -> tuple[str, str]:
    paper_excerpt = _trim_paper_text(raw_text)
    user_prompt = (
        "Here is the extracted text of a research paper. Classify it.\n\n"
        f"{paper_excerpt}"
    )
    return _CLASSIFY_SYSTEM_PROMPT, user_prompt
