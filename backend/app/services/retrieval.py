"""
Track C — lightweight, keyword-based retrieval (BM25) over a paper's
chunks.

Deliberately not embeddings-based: embeddings would mean either another
API call per chunk (more free-tier LLM budget spent per upload) or a
new external service. BM25 is pure-python, instant, and good enough for
the "one paper's worth of context" scope this assistant is built for.
"""
from rank_bm25 import BM25Okapi


def retrieve_relevant_chunks(question: str, chunks: list[dict], top_k: int = 4) -> list[dict]:
    """
    Returns up to top_k chunks most relevant to the question. Falls back
    to the first top_k chunks if nothing scores above zero (e.g. very
    short/odd questions) so the assistant still has *some* context
    rather than none.
    """
    if not chunks:
        return []

    # Include the section name in what BM25 indexes (not in what's sent to
    # the LLM as context) so a question like "what's the conclusion" can
    # match the Conclusion section even if its body text never uses that
    # word literally.
    tokenized_corpus = [
        (c["section"].lower() + " " + c["text"].lower()).split() for c in chunks
    ]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(question.lower().split())

    ranked = sorted(zip(chunks, scores), key=lambda pair: pair[1], reverse=True)
    top_scored = [chunk for chunk, score in ranked[:top_k] if score > 0]

    if top_scored:
        return top_scored
    return [chunk for chunk, _ in ranked[:top_k]]
