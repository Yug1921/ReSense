"""
Track C — keyword retrieval (BM25) over a paper's passages.

Deliberately not embeddings-based: embeddings would mean another API call
per passage (more free-tier budget per upload) or a new external service.
BM25 is pure Python and instant. To make keyword search work for how
people actually ask, words are reduced to a simple stem ("filtering",
"filters" -> "filter"), common words are ignored, and broad questions
("what are the main results?") also pull in the abstract and conclusion,
where papers state their findings, whatever words they use.
"""
import re

from rank_bm25 import BM25Okapi

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "for", "with", "as", "by",
    "is", "are", "was", "were", "be", "been", "it", "its", "this", "that", "these", "those",
    "what", "which", "who", "whom", "how", "why", "when", "where", "does", "do", "did", "can",
    "could", "would", "should", "will", "paper", "papers", "author", "authors", "they", "their",
    "there", "about", "from", "at", "into", "me", "you", "your", "i", "we", "our", "us", "tell",
    "explain", "describe", "give", "list", "please", "any", "some", "all", "has", "have", "had",
    "so", "if", "than", "then", "also", "such", "used", "use", "using", "study", "work",
}
_WORD_RE = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")

# Broad questions whose answer lives in the abstract/conclusion more than in
# any passage that shares their words.
_OVERVIEW_RE = re.compile(
    r"\b(main|key|overall|summar|result|finding|conclu|contribut|takeaway|problem|purpose|goal|"
    r"aim|objective|about|novel|propos|significan|outcome|tl;?dr|gist|overview)",
    re.IGNORECASE,
)
_LIMITATION_RE = re.compile(r"\b(limitation|weakness|shortcoming|drawback|future|gap|critic)", re.IGNORECASE)
_METHOD_RE = re.compile(r"\b(method|approach|how did|how does|technique|algorithm|architecture|model|procedure|design)", re.IGNORECASE)
_SECTION_HINTS = (
    (_OVERVIEW_RE, ("opening page", "abstract", "conclusion", "summary", "discussion", "outlook")),
    (_LIMITATION_RE, ("limitation", "discussion", "conclusion", "future", "shortcoming", "outlook")),
    (_METHOD_RE, ("method", "approach", "model", "architecture", "experiment", "setup")),
)


def _stem(word: str) -> str:
    """Light stemming so "filters", "filtered" and "filtering" all match "filter"."""
    if len(word) <= 4 or not word.isalpha():
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    if re.search(r"(ch|sh|x|ss)es$", word):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    return [_stem(w) for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS]


def retrieve_relevant_chunks(
    question: str,
    chunks: list[dict],
    top_k: int = 4,
    context: str = "",
) -> list[dict]:
    """
    Up to top_k passages most relevant to the question, best first.

    context: the previous question, for follow-ups such as "and the second
    one?"; its words count for less than the question's own.
    Falls back to the first passages when nothing matches, so the assistant
    always has some context.
    """
    if not chunks:
        return []

    corpus = [tokenize(c["section"] + " " + c["section"] + " " + c["text"]) for c in chunks]
    bm25 = BM25Okapi(corpus)
    query = tokenize(question)
    scores = list(bm25.get_scores(query)) if query else [0.0] * len(chunks)
    if context:
        follow_up = bm25.get_scores(tokenize(context))
        scores = [s + 0.35 * f for s, f in zip(scores, follow_up)]

    # Boost the sections where broad questions are answered.
    top = max(scores) if scores else 0
    for pattern, hints in _SECTION_HINTS:
        if pattern.search(question):
            for index, chunk in enumerate(chunks):
                if any(hint in chunk["section"].lower() for hint in hints):
                    scores[index] += max(top * 0.6, 1.0)

    # The abstract states the paper's purpose and headline numbers, and helps
    # almost every question, so it is always included.
    abstract = [i for i, c in enumerate(chunks) if c["section"].lower() == "abstract"][:2] or [
        i for i, c in enumerate(chunks) if c["section"].lower() == "opening page"
    ][:2]
    ranked = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
    best = [i for i in ranked if scores[i] > 0 and i not in abstract][: max(top_k - len(abstract), 1)]
    if not best:
        return [chunks[i] for i in abstract] + chunks[:top_k][: top_k - len(abstract)]
    return [chunks[i] for i in sorted(abstract, key=lambda i: -scores[i])] + [chunks[i] for i in best]
