"""
Track C — splits a paper's cached text into retrieval-sized chunks.

Uses the structure detected at upload time (Track A) when available, so
chunks stay aligned to actual sections (nicer for citing "from the
Methodology section" in answers). Falls back to plain word-window
chunking for papers where structure detection found nothing.
"""

_TARGET_WORDS_PER_CHUNK = 220


def chunk_paper(raw_text: str, structure: dict | None) -> list[dict]:
    """Returns a list of {"section": str, "text": str} chunks."""
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

    return chunks
