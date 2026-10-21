"""
Single, shared entry point for every text-generation call in the app.

Claude answers first when ANTHROPIC_API_KEY is set; otherwise (or if Claude
fails) the free OpenRouter / Groq / Gemini chain is tried in order.

Deliberately conservative: one retry with backoff, a hard timeout, and
no fan-out of parallel calls per user action. Every feature (summarize,
and later ask/analyze) should go through `call_openrouter` rather than
hitting httpx directly, so rate-limit behavior stays consistent
app-wide.
"""
import re

import anthropic
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

_NO_REASONING_SUFFIX = (
    "\n\nIMPORTANT: Output ONLY your final answer, directly and immediately. "
    "Do not include any internal reasoning, planning notes, or meta-commentary "
    "(e.g. never write things like 'We need to...', 'Let me think...', 'The task "
    "is...'). Do not narrate your thought process — just give the finished answer."
)


def _strip_leaked_reasoning(content: str) -> str:
    """Safety net: strip an explicit reasoning block emitted by a model."""
    if not content:
        return content
    return _THINK_TAG_RE.sub("", content).strip()


class LLMRequestError(Exception):
    """Raised when OpenRouter fails after retrying — surface this as a
    friendly 'the assistant is busy, please try again' message, never a
    raw 500."""


class LLMRateLimitError(LLMRequestError):
    """Raised specifically on HTTP 429 so callers can show rate-limit-
    specific messaging instead of a generic error."""


class LLMProviderUnavailableError(LLMRequestError):
    """Raised for temporary provider overload or gateway failures."""


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
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
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if response.status_code == 429:
        raise LLMRateLimitError(
            "Rate limit hit on this provider. Trying the next one."
        )
    if response.status_code in {502, 503, 504}:
        raise LLMProviderUnavailableError(
            f"Provider temporarily unavailable ({response.status_code})."
        )
    if response.status_code >= 400:
        raise LLMRequestError(f"Provider error {response.status_code}: {response.text[:300]}")
    return response.json()


_claude_client: anthropic.AsyncAnthropic | None = None


def _claude() -> anthropic.AsyncAnthropic:
    global _claude_client
    if _claude_client is None:
        _claude_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=60.0)
    return _claude_client


async def _call_claude(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    """One Claude call. Raises LLMRequestError so the caller can fall back."""
    try:
        response = await _claude().messages.create(
            model=settings.anthropic_model,
            # Room for the model's short thinking on top of the answer itself.
            max_tokens=max_tokens + 2000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            # Summaries and answers are routine work: low effort keeps them fast and cheap.
            output_config={"effort": "low"},
        )
    except anthropic.RateLimitError as exc:
        raise LLMRateLimitError(f"Claude rate limit: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise LLMRequestError(f"Claude error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMProviderUnavailableError(f"Claude unreachable: {exc}") from exc

    if response.stop_reason == "refusal":
        raise LLMRequestError("Claude declined this request.")
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        raise LLMRequestError(f"Claude returned no text (stop reason: {response.stop_reason}).")
    return text


async def call_openrouter(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 900,
    temperature: float = 0.4,
) -> str:
    """
    Tries each configured provider and model in order, continuing to the
    next provider when a model is unavailable, rate-limited, or errors.
    """
    payload_base = {
        "messages": [
            {"role": "system", "content": system_prompt + _NO_REASONING_SUFFIX},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "reasoning_effort": "low",
    }

    last_error: Exception | None = None
    if settings.anthropic_api_key:
        try:
            return await _call_claude(system_prompt, user_prompt, max_tokens)
        except LLMRequestError as exc:
            last_error = exc  # fall back to the free providers

    for provider in settings.provider_chain:
        try:
            data = await _post_chat_completion(
                {**payload_base, "model": provider["model"]},
                provider["base_url"],
                provider["api_key"],
            )
            content = data["choices"][0]["message"]["content"]
            content = _strip_leaked_reasoning(content)
            if not content:
                raise LLMRequestError(f"Model '{provider['model']}' returned empty content.")
            return content.strip()
        except (LLMRequestError, KeyError, IndexError, AttributeError, TypeError, httpx.TransportError,) as exc:
            last_error = exc
            continue  # try the next model in the chain

    raise LLMRequestError(
        f"All configured providers failed. Last error: {last_error}"
    ) from last_error
