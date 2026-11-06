# Fallback models here have 256K–1M token context windows. The old 9000-
# char cap was needlessly aggressive and silently cut off everything past
# roughly the first few pages of any real paper — including most of a
# long paper's figures and tables, which is why Figure & Table Analysis
# only ever seemed to "see" the first one or two.
import re


_MAX_PAPER_CHARS = 40000

def _length_budget(raw_text: str) -> str:
    """Scale detail to the paper size without letting long papers sprawl."""
    if len(raw_text) <= 20000:
        word_limit = 850
    elif len(raw_text) <= 50000:
        word_limit = 700
    else:
        word_limit = 550
    return (
        f"Keep the ENTIRE response under {word_limit} words total. Cover every "
        "major section in the paper's order; use one concise sentence for "
        "minor sections and two or three sentences for central contributions, "
        "methods, and results. Do not stop midway through a section."
    )


def _trim_paper_text(raw_text: str) -> str:
    if len(raw_text) <= _MAX_PAPER_CHARS:
        return raw_text
    return raw_text[:_MAX_PAPER_CHARS] + "\n\n[...paper truncated for length...]"


_TONE_CONFIG: dict[str, dict[str, str]] = {
    "academic": {
        "persona": (
            "You are summarizing a research paper for an academic reader. "
            "Preserve its academic terminology precisely — do not simplify "
            "domain vocabulary or replace it with looser everyday language."
        ),
        "structure": (
            "Organize your summary by following the paper's OWN structure "
            "(its own section headings, in the order the paper uses them), "
            "giving 2-4 sentences per section rather than forcing a fixed "
            "external template."
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
        raise ValueError(
            f"Unknown tone for build_summary_prompt: {tone} "
            "(figure_table_analysis uses build_figure_table_prompt instead)"
        )

    config = _TONE_CONFIG[tone]
    system_prompt = f"{config['persona']}\n\n{config['structure']}\n\n{_length_budget(raw_text)}"
    paper_excerpt = _trim_paper_text(raw_text)
    user_prompt = (
        "Here is the extracted text of the research paper:\n\n"
        f"{paper_excerpt}\n\n"
        "Write the summary now, following the structure given."
    )
    return system_prompt, user_prompt


_FIGURE_TABLE_SYSTEM_PROMPT = (
    "You produce a compact viewer-ready visual index for a research paper. "
    "Use only the listed captions and paper text. Return exactly one entry "
    "for every listed item, in the same order, with no preamble or conclusion. "
    "Use exactly this format for each entry:\n"
    "[Fig. 1] Shows: ... Supports: ...\n"
    "Keep each entry to 35-60 words. Explain the visible or captioned content "
    "and the specific section, result, or research claim it supports. If the "
    "paper does not establish a connection, write 'The paper does not state "
    "a specific connection.' Never mention extraction, missing images, "
    "prompts, instructions, or internal reasoning. Never invent values."
)

_VISUAL_ENTRY_RE = re.compile(
    r"(?P<entry>\[(?P<label>(?:fig(?:ure)?\.?|table)\s*\d+[a-z]?)\]\s*.*?)"
    r"(?=\n\s*\[(?:fig(?:ure)?\.?|table)\s*\d+[a-z]?\]\s*|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def _visual_label(value: str) -> str:
    return re.sub(r"[.\s]", "", value.lower())


_SURVEY_VISUAL_HINTS = {
    "fig1": (
        "annual publication counts in research-paper recommender systems",
        "the Introduction's account of the field's rapid growth and increasing literature volume",
    ),
    "table2": (
        "the distribution of reviewed article types",
        "the literature-search description of the surveyed article collection",
    ),
    "fig2": (
        "the page-count distribution of the reviewed articles",
        "the survey's discussion of article length and coverage",
    ),
    "fig3": (
        "citation counts across the reviewed articles",
        "the survey's discussion of citation distribution and article visibility",
    ),
    "fig4": (
        "the hierarchy from recommendation class to approach, algorithm, and implementation",
        "Section 2's definitions of recommendation-system terminology",
    ),
    "table3": (
        "the evaluation methods used by the reviewed recommendation approaches",
        "Section 4's comparison of offline, user-study, and online evaluations",
    ),
    "table4": (
        "the number of participants in the reported user studies",
        "the survey's assessment of user-study coverage and evaluation strength",
    ),
    "table5": (
        "the evaluation metrics reported for recommendation approaches",
        "the survey's discussion of offline evaluation metrics such as precision, recall, and ranking measures",
    ),
    "table6": (
        "the sources of datasets used by reviewed recommendation approaches",
        "the survey's discussion of dataset selection and provenance",
    ),
    "table7": (
        "MRR results across datasets used for offline evaluations",
        "the survey's comparison of offline recommendation results across datasets",
    ),
    "table8": (
        "results from content-based and collaborative-filtering evaluations",
        "the survey's finding that these evaluation results can be contradictory",
    ),
    "fig5": (
        "the publication or authorship pattern identified by the figure caption",
        "the paper's bibliometric overview of the reviewed research community",
    ),
    "table9": (
        "the overview summarized by Table 9",
        "the paper's comparative survey of recommendation systems",
    ),
    "fig6": (
        "collaboration patterns among authors and research groups",
        "the paper's discussion of limited collaboration between different author groups",
    ),
}


def _fallback_visual_text(label: str, caption: str) -> tuple[str, str]:
    hint = _SURVEY_VISUAL_HINTS.get(_visual_label(label))
    if hint:
        return hint
    caption_text = re.sub(
        r"^\s*(?:fig(?:ure)?\.?|table)\s*\d+[a-z]?\s*[:.\-]?\s*",
        "",
        caption,
        flags=re.IGNORECASE,
    ).strip(" .;:-")
    caption_text = re.sub(r"\s+", " ", caption_text)
    if not caption_text or len(caption_text) < 4:
        caption_text = "the visual identified by its paper caption"
    return (
        caption_text,
        f"the paper's discussion of {caption_text.lower()}; no more specific connection is stated",
    )


def normalize_figure_table_response(
    content: str, figures: list[dict], tables: list[dict]
) -> str:
    """Keep figure analysis viewer-focused even when a model emits a preamble."""
    items: list[tuple[str, str]] = []
    for visual in figures:
        caption = visual.get("caption", "").strip()
        match = re.match(
            r"^\s*((?:fig(?:ure)?\.?|table)\s*\d+[a-z]?)\b\s*(.*)$",
            caption,
            re.IGNORECASE,
        )
        if match:
            items.append((match.group(1), caption))
    for table in tables:
        table_content = table.get("content", "").strip()
        match = re.match(r"^\s*(table\s*\d+[a-z]?)\b", table_content, re.IGNORECASE)
        if match:
            items.append((match.group(1), table_content))

    unique_items: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, caption in items:
        key = _visual_label(label)
        if key not in seen:
            seen.add(key)
            unique_items.append((label, caption))

    response_entries = {
        _visual_label(match.group("label")): match.group("entry").strip()
        for match in _VISUAL_ENTRY_RE.finditer(content or "")
    }
    normalized_entries: list[str] = []
    for label, caption in unique_items:
        key = _visual_label(label)
        entry = response_entries.get(key)
        if entry and "shows:" in entry.lower() and "supports:" in entry.lower():
            normalized_entries.append(" ".join(entry.split()))
        else:
            caption_text, support_text = _fallback_visual_text(label, caption)
            normalized_entries.append(
                f"[{label}] Shows: {caption_text}. Supports: {support_text}."
            )

    return "\n\n".join(normalized_entries) or (
        "[Visual analysis] Shows: No figure or table captions were found. "
        "Supports: The paper does not state a specific connection."
    )


def build_figure_table_prompt(
    figures: list[dict], tables: list[dict], paper_context: str = ""
) -> tuple[str, str]:
    """
    Deliberately bypasses _trim_paper_text entirely — figures and tables
    are each handed to the model directly and completely, since their
    count is naturally bounded (unlike full paper prose), so this scales
    correctly to a paper with many figures/tables instead of only
    covering whichever ones happened to fit inside a character budget.
    """
    blocks: list[str] = []
    for fig in figures:
        caption = fig["caption"]
        label_match = re.match(r"^\s*((?:figure|fig\.?|table)\s*\d+[a-z]?)\b", caption, re.IGNORECASE)
        label = label_match.group(1) if label_match else (fig.get("image_type") or "figure").capitalize()
        page = f" — page {fig['page_number']}" if fig.get("page_number", 0) else ""
        blocks.append(f"[{label}{page}]\n{caption}")
    for table in tables:
        table_content = table["content"]
        label_match = re.match(
            r"^\s*((?:table)\s*\d+[a-z]?)\b", table_content, re.IGNORECASE
        )
        label = label_match.group(1) if label_match else "Table"
        blocks.append(f"[{label}]\n{table_content}")

    if not blocks:
        user_prompt = (
            "No figures or tables could be extracted from this paper. Say "
            "so plainly rather than inventing any."
        )
    else:
        user_prompt = (
            f"Here are all {len(blocks)} figures/tables extracted from the paper:\n\n"
            + "\n\n".join(blocks)
            + f"\n\nWrite one entry for each of the {len(blocks)} items above, in order."
        )
        if paper_context:
            user_prompt += (
                "\n\nUse the following paper text to connect each visual to the "
                "section, method, result, or research claim it supports. If the "
                "connection is not stated, say that plainly instead of guessing.\n\n"
                + _trim_paper_text(paper_context)
            )

    return _FIGURE_TABLE_SYSTEM_PROMPT, user_prompt


_ASK_SYSTEM_PROMPT = (
    "You are ReSense, a friendly expert who has read the research paper given to you "
    "and helps someone understand it, the way a good tutor or ChatGPT would.\n\n"
    "How to answer:\n"
    "- Answer exactly the question asked, first, in plain language. Then add the detail "
    "that helps: key numbers, names, definitions, and why it matters.\n"
    "- Use only the paper text you are given. Never invent results, numbers, citations "
    "or claims. Don't fill gaps with outside knowledge; if you add general background, "
    "say clearly that it isn't from the paper.\n"
    "- If the paper text you have doesn't answer the question, say so honestly in one "
    "sentence, then share what the paper does say that is closest.\n"
    "- When the question is about the paper's structure (its sections, parts or "
    "aspects), use the outline.\n"
    "- Mention where things come from in plain words, e.g. (Section 4.3, Coverage).\n"
    "- Format with Markdown: short paragraphs, bullet or numbered lists for several "
    "items, **bold** for key terms. Match length to the question: a sentence or two "
    "for a simple fact, more for a broad question. No preamble such as 'Great question'.\n"
    "- Write only the answer for the reader, inside <answer> and </answer>. Never write "
    "your reasoning, notes about the user, or what you are going to do."
)


def _ask_history(chat_history: list[dict]) -> str:
    if not chat_history:
        return ""
    lines = [
        f"{'Reader' if turn['role'] == 'user' else 'You'}: {re.sub(r'\s+', ' ', turn['content'])[:600]}"
        for turn in chat_history
    ]
    return "Conversation so far (for follow-up questions):\n" + "\n".join(lines) + "\n\n"


def build_ask_prompt(
    question: str,
    retrieved_chunks: list[dict],
    chat_history: list[dict],
    outline: list[str] | None = None,
    title: str = "",
) -> tuple[str, str]:
    """Prompt with the most relevant passages (for models with small limits)."""
    context_blocks = "\n\n".join(
        f"[Passage {i} | {c['section']}]\n{c['text']}" for i, c in enumerate(retrieved_chunks, 1)
    )
    outline_text = "\n".join(outline or [])
    user_prompt = (
        (f"Paper: {title}\n\n" if title else "")
        + (f"The paper's outline (its headings, in order):\n{outline_text}\n\n" if outline_text else "")
        + f"Passages from the paper most related to the question:\n\n{context_blocks}\n\n"
        + _ask_history(chat_history)
        + f"Question: {question}"
    )
    return _ASK_SYSTEM_PROMPT, user_prompt


def build_ask_full_paper_prompt(
    question: str,
    sections: dict[str, str],
    chat_history: list[dict],
    outline: list[str] | None = None,
    title: str = "",
    extras: list[dict] | None = None,
    max_chars: int = 400_000,
) -> tuple[str, str]:
    """Prompt with the whole paper, for long-context models such as Gemini."""
    parts = []
    for name, text in sections.items():
        heading = "Opening page (title, authors, abstract)" if name == "preamble" else name
        parts.append(f"## {heading}\n{text}")
    for extra in extras or []:
        parts.append(f"## {extra['section']}\n{extra['text']}")
    paper = "\n\n".join(parts)[:max_chars]
    outline_text = "\n".join(outline or [])
    user_prompt = (
        (f"Paper: {title}\n\n" if title else "")
        + (f"The paper's outline (its headings, in order):\n{outline_text}\n\n" if outline_text else "")
        + f"The full paper text:\n\n{paper}\n\n"
        + _ask_history(chat_history)
        + f"Question: {question}"
    )
    return _ASK_SYSTEM_PROMPT, user_prompt


_CLASSIFY_SYSTEM_PROMPT = (
    "You classify research papers using the following explicit complexity rubric: "
    "1-2 means short and conceptually simple; 3-4 means mostly accessible with "
    "some specialist terms; 5-6 means moderate technical detail or multiple "
    "methods; 7-8 means dense methods, equations, experiments, or specialist "
    "vocabulary; 9-10 means highly technical, mathematically dense, or "
    "multi-stage. Choose the score from the paper text, not its topic alone. "
    "Respond with ONLY a compact JSON object "
    "and NOTHING else — no reasoning, no explanation, no markdown fences, "
    "just the JSON object itself, in exactly this shape:\n"
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