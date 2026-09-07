_MAX_PAPER_CHARS = 9000
_LENGTH_BUDGET = (
    "Keep the ENTIRE response under 300 words total — stay within that "
    "budget rather than running long, since the response will be cut off "
    "if it exceeds it."
)


def _trim_paper_text(raw_text: str) -> str:
    if len(raw_text) <= _MAX_PAPER_CHARS:
        return raw_text
    return raw_text[:_MAX_PAPER_CHARS] + "\n\n[...paper truncated for length...]"


# Each tone gets its own (persona, structure) pair rather than one shared
# template — the five tones are meant to shape different structures, not
# just different reading levels of the same five-part outline.
_TONE_CONFIG: dict[str, dict[str, str]] = {
    "academic": {
        "persona": (
            "You are summarizing a research paper for an academic reader. "
            "Preserve its academic terminology precisely — do not simplify "
            "domain vocabulary or replace it with looser everyday language."
        ),
        "structure": (
            "Organize your summary by following the paper's OWN structure "
            "(its own section headings, in the order the paper uses them — "
            "e.g. Introduction, Related Work, Method, Results, Discussion, "
            "whatever the paper actually has), giving 2-4 sentences per "
            "section rather than forcing a fixed external template."
        ),
    },
    "technical": {
        "persona": (
            "You are summarizing a research paper for a practitioner who "
            "wants the technical substance, not motivational framing."
        ),
        "structure": (
            "Structure your response under these labeled parts, 2-4 "
            "sentences each:\n"
            "1. Algorithm(s) / architecture used\n"
            "2. Dataset(s) and preprocessing\n"
            "3. Key equations and parameters\n"
            "4. Evaluation metrics and reported results"
        ),
    },
    "research_insight": {
        "persona": (
            "You are summarizing a research paper to surface its research "
            "framing, for a reader who wants to understand the paper's "
            "place in its field, not its technical mechanics."
        ),
        "structure": (
            "Structure your response under these labeled parts, 2-4 "
            "sentences each:\n"
            "1. Research problem being addressed\n"
            "2. Gap in prior work this targets\n"
            "3. Novelty / contribution of this paper's approach\n"
            "4. Key assumptions it relies on\n"
            "5. Why this work is significant"
        ),
    },
    "figure_table_analysis": {
        "persona": (
            "You are summarizing a research paper with a focus on its "
            "figures and tables, for a reader who wants to know what the "
            "paper's visual evidence shows."
        ),
        "structure": (
            "List each figure or table you can identify from the text "
            "(captions, in-text references like 'Figure 2 shows...' or "
            "'Table 1 lists...'), one per line, each covering: what it "
            "shows, and which section or research claim it supports. If "
            "the extracted text doesn't let you identify specific figures "
            "or tables, say so plainly rather than inventing them."
        ),
    },
    "critical_review": {
        "persona": (
            "You are critically reviewing a research paper. Be fair but "
            "genuinely critical, not just summarizing positively."
        ),
        "structure": (
            "Structure your response under these labeled parts, 2-4 "
            "sentences each:\n"
            "1. What the authors demonstrate (backed by reported "
            "experiments/results)\n"
            "2. What they merely claim or assert without clearly shown "
            "evidence\n"
            "3. Experimental concerns (sample size, baselines, statistical "
            "rigor)\n"
            "4. Overall validity verdict on the conclusions"
        ),
    },
}


def build_summary_prompt(tone: str, raw_text: str) -> tuple[str, str]:
    if tone not in _TONE_CONFIG:
        raise ValueError(f"Unknown tone: {tone}")

    config = _TONE_CONFIG[tone]
    system_prompt = f"{config['persona']}\n\n{config['structure']}\n\n{_LENGTH_BUDGET}"
    paper_excerpt = _trim_paper_text(raw_text)
    user_prompt = (
        "Here is the extracted text of the research paper:\n\n"
        f"{paper_excerpt}\n\n"
        "Write the summary now, following the structure given."
    )
    return system_prompt, user_prompt


def build_ask_prompt(
    question: str, relevant_chunks: list[dict], chat_history: list[dict]
) -> tuple[str, str]:
    context = "\n\n".join(
        f"[{chunk['section']}]\n{chunk['text']}" for chunk in relevant_chunks
    ) or "No relevant paper excerpts were found."
    history = "\n".join(
        f"{turn['role'].capitalize()}: {turn['content']}" for turn in chat_history
    ) or "No previous conversation."
    system_prompt = (
        "You answer questions about a research paper using only the supplied excerpts. "
        "If the excerpts do not support an answer, say so plainly. Do not invent facts."
    )
    user_prompt = (
        f"Previous conversation:\n{history}\n\n"
        f"Relevant paper excerpts:\n{context}\n\n"
        f"Question: {question}"
    )
    return system_prompt, user_prompt


def build_classification_prompt(raw_text: str) -> tuple[str, str]:
    paper_excerpt = _trim_paper_text(raw_text)
    return (
        "Classify the research paper using only the provided text. Return valid JSON "
        "with exactly these keys: paper_type, complexity, complexity_score. "
        "complexity must be low, medium, or high; complexity_score must be an integer from 1 to 10.",
        f"Research paper text:\n\n{paper_excerpt}",
    )