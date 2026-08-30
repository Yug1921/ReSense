"""
Track C — splits a paper's cached text into retrieval-sized chunks.

Uses the structure detected at upload time (Track A) when available, so
chunks stay aligned to actual sections (nicer for citing "from the
Methodology section" in answers). Falls back to plain word-window
chunking for papers where structure detection found nothing.
"""

_TARGET_WORDS_PER_CHUNK = 220


_TARGET_WORDS_PER_CHUNK = 220


def chunk_paper(raw_text: str, structure: dict | None, figures: list[dict] | None = None) -> list[dict]:
    """
    figures: optional list of {page_number, image_type, caption} for
    already-captioned figures (see Track J / /figures). Each captioned
    figure becomes its own small chunk, so a question like "what does
    table 2 show" or "what does the code snippet do" can be answered
    from the vision model's caption the same way a text question is
    answered from the paper's own text.
    """
    sections = (structure or {}).get("sections")
    chunks: list[dict] = []

    if sections:
        for name, text in sections.items():
            words = text.split()
            if not words:
                continue
            for i in range(0, len(words), _TARGET_WORDS_PER_CHUNK):
                piece = " ".join(words[i : i + _TARGET_WORDS_PER_CHUNK])
                chunks.append({"section": name, "text": piece})
    else:
        words = raw_text.split()
        for i in range(0, len(words), _TARGET_WORDS_PER_CHUNK):
            piece = " ".join(words[i : i + _TARGET_WORDS_PER_CHUNK])
            chunks.append({"section": "paper", "text": piece})

    if not chunks and raw_text.strip():
        chunks.append({"section": "paper", "text": raw_text})

    for fig in figures or []:
        if not fig.get("caption"):
            continue
        label = f"{(fig.get('image_type') or 'figure').capitalize()} on page {fig['page_number']}"
        chunks.append({"section": label, "text": fig["caption"]})

    return chunks
