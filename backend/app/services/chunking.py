_TARGET_WORDS_PER_CHUNK = 220


def chunk_paper(raw_text: str, structure: dict | None, extra_chunks: list[dict] | None = None) -> list[dict]:
    """
    extra_chunks: additional {section, text} chunks to fold in on top of
    the paper's own text — e.g. captioned figures AND extracted tables —
    so /ask can retrieve and answer from them the same way it answers
    from the paper's prose.
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

    chunks.extend(extra_chunks or [])
    return chunks