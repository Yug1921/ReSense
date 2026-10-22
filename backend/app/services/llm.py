"""
Single, shared entry point for every text-generation call in the app.

Tries free models on Gemini, Groq and OpenRouter in turn (see providers.py
for how they are chosen), moving to the next one whenever a model is busy,
over its limit, retired, or errors, so an answer comes back as long as any
of them still has free quota left.
"""
import logging
import re

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings
from app.services import providers

logger = logging.getLogger(__name__)

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

_NO_REASONING_SUFFIX = (
    "\n\nIMPORTANT: Output ONLY your final answer, directly and immediately. "
    "Do not include any internal reasoning, planning notes, or meta-commentary "
    "(e.g. never write things like 'We need to...', 'Let me think...', 'The task "
    "is...'). Do not narrate your thought process — just give the finished answer."
)


_ANSWER_TAG_RE = re.compile(r"<answer>(.*?)(?:</answer>|$)", re.DOTALL | re.IGNORECASE)
# Openings that mean a model is thinking out loud instead of answering.
_REASONING_START_RE = re.compile(
    r"^\W*(?:the user (?:is asking|asks|wants|has asked)|the question (?:is asking|asks)|"
    r"we need to|i need to|i should|let me|let's (?:look|see|think|review)|okay,? (?:so|let)|"
    r"alright,? |first,? i|to answer this,? i|my task is|the task is)",
    re.IGNORECASE,
)


class LeakedReasoningError(Exception):
    pass


def _strip_leaked_reasoning(content: str) -> str:
    """Return only the answer: drop <think> blocks, unwrap <answer> tags,
    and reject replies that are the model's reasoning rather than an answer."""
    if not content:
        return content
    content = _THINK_TAG_RE.sub("", content).strip()
    tagged = _ANSWER_TAG_RE.findall(content)
    if tagged and tagged[-1].strip():
        return tagged[-1].strip()
    content = re.sub(r"</?answer>", "", content, flags=re.IGNORECASE).strip()
    if _REASONING_START_RE.match(content):
        raise LeakedReasoningError("The model wrote its reasoning instead of an answer.")
    return content


class LLMRequestError(Exception):
    """Raised when OpenRouter fails after retrying — surface this as a
    friendly 'the assistant is busy, please try again' message, never a
    raw 500."""


class LLMRateLimitError(LLMRequestError):
    """Raised specifically on HTTP 429 so callers can show rate-limit-
    specific messaging instead of a generic error."""


class LLMProviderUnavailableError(LLMRequestError):
    """Raised for temporary provider overload or gateway failures."""


class LLMModelGoneError(LLMRequestError):
    """The model doesn't exist (any more) for this key."""


class LLMRequestTooLargeError(LLMRequestError):
    """The request is bigger than this model's free limit allows."""


# How long to skip a model after each kind of failure (seconds).
_REST_RATE_LIMITED = 60
_REST_DAILY_LIMIT = 3600
_REST_GONE = 6 * 3600
_REST_ERROR = 120

# Gemini says "...PerDay...", Groq "tokens per day", OpenRouter "free-models-per-day".
_DAILY_LIMIT_RE = re.compile(r"per[\s_-]?day|daily", re.IGNORECASE)
_GONE_HINTS = ("not found", "does not exist", "decommissioned", "deprecated", "no endpoints", "not supported")


@retry(
    reraise=True,
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=6),
    retry=retry_if_exception_type((httpx.TransportError, LLMProviderUnavailableError)),
)
async def _post_chat_completion(
    payload: dict,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict:
    base_url = base_url or settings.openrouter_base_url
    api_key = api_key or settings.openrouter_api_key
    # Long papers take a while to summarize; a short timeout cut them off.
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if response.status_code == 429:
        raise LLMRateLimitError(f"Rate limit hit: {response.text[:300]}")
    if response.status_code == 413:
        raise LLMRequestTooLargeError(f"Request too large: {response.text[:300]}")
    if response.status_code == 404 or (
        response.status_code == 400 and any(h in response.text.lower() for h in _GONE_HINTS)
    ):
        raise LLMModelGoneError(f"Model unavailable ({response.status_code}): {response.text[:300]}")
    if response.status_code in {502, 503, 504}:
        raise LLMProviderUnavailableError(
            f"Provider temporarily unavailable ({response.status_code})."
        )
    if response.status_code >= 400:
        raise LLMRequestError(f"Provider error {response.status_code}: {response.text[:300]}")
    return response.json()


def _rest_seconds(exc: Exception) -> float:
    text = str(exc).lower()
    if isinstance(exc, LLMRateLimitError):
        return _REST_DAILY_LIMIT if _DAILY_LIMIT_RE.search(text) else _REST_RATE_LIMITED
    if isinstance(exc, LLMModelGoneError):
        return _REST_GONE
    if isinstance(exc, LLMRequestTooLargeError):
        return 0  # fine for smaller requests
    return _REST_ERROR


async def call_openrouter(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 900,
    temperature: float = 0.4,
    long_context_user_prompt: str | None = None,
) -> str:
    """
    Ask the best available free model, falling through the ranked list
    (providers.candidates) until one answers.

    long_context_user_prompt: a fuller prompt (e.g. the whole paper) sent
    instead of user_prompt to models with a very long context (Gemini).
    """
    messages = [
        {"role": "system", "content": system_prompt + _NO_REASONING_SUFFIX},
        {"role": "user", "content": user_prompt},
    ]
    # Rough size: about four characters per token, plus room for the reply.
    estimated_tokens = (len(system_prompt) + len(user_prompt)) // 4 + max_tokens

    candidates = await providers.candidates(estimated_tokens)
    choice = providers.chosen_provider.get()
    if not candidates and choice == "groq" and estimated_tokens > providers.GROQ_MAX_REQUEST_TOKENS:
        raise LLMRequestError(
            "This is too long for Groq's free plan (about 8,000 tokens a minute). "
            "Pick Automatic or Gemini in the AI menu for whole-paper tasks."
        )
    if not candidates and choice in providers.PROVIDERS:
        raise LLMRequestError(
            f"No {choice.capitalize()} model is available right now (no key, or all at their limit). "
            "Pick Automatic in the AI menu to use the others."
        )
    if not candidates:
        raise LLMRequestError(
            "No AI model is available: add a Gemini, Groq or OpenRouter key to backend/.env, "
            "or wait for the free limits to reset."
        )

    last_error: Exception | None = None
    rate_limited = 0
    for candidate in candidates:
        candidate_messages = messages
        if long_context_user_prompt and candidate.provider == "gemini":
            candidate_messages = [messages[0], {"role": "user", "content": long_context_user_prompt}]
        payload = {
            "model": candidate.model,
            "messages": candidate_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **providers.request_options(candidate),
        }
        try:
            data = await _post_chat_completion(payload, candidate.base_url, candidate.api_key)
            try:
                content = _strip_leaked_reasoning(data["choices"][0]["message"]["content"] or "")
            except LeakedReasoningError as exc:
                raise LLMRequestError(f"{candidate.key}: {exc}") from exc
            if not content:
                raise LLMRequestError(f"{candidate.key} returned an empty reply.")
            return content.strip()
        except (LLMRequestError, KeyError, IndexError, AttributeError, TypeError, httpx.TransportError) as exc:
            last_error = exc
            rate_limited += isinstance(exc, LLMRateLimitError)
            seconds = _rest_seconds(exc)
            if seconds:
                providers.rest(candidate, seconds)
            logger.warning("AI model %s failed, trying the next one: %s", candidate.key, exc)

    if rate_limited == len(candidates):
        raise LLMRateLimitError("Every free AI model is at its limit right now. Try again in a minute.")
    raise LLMRequestError(f"All free AI models failed. Last error: {last_error}") from last_error
