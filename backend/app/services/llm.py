"""
Single, shared entry point for every OpenRouter call in the app.

Deliberately conservative: one retry with backoff, a hard timeout, and
no fan-out of parallel calls per user action. Every feature (summarize,
and later ask/analyze) should go through `call_openrouter` rather than
hitting httpx directly, so rate-limit behavior stays consistent
app-wide.
"""
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings


class LLMRequestError(Exception):
    """Raised when OpenRouter fails after retrying — surface this as a
    friendly 'the assistant is busy, please try again' message, never a
    raw 500."""


class LLMRateLimitError(LLMRequestError):
    """Raised specifically on HTTP 429 so callers can show rate-limit-
    specific messaging instead of a generic error."""


@retry(
    reraise=True,
    stop=stop_after_attempt(2),  # one retry, not aggressive backoff-spam
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(httpx.TransportError),
)
async def _post_chat_completion(payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.openrouter_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if response.status_code == 429:
        raise LLMRateLimitError(
            "OpenRouter rate limit hit. Please wait a few seconds and try again."
        )
    if response.status_code >= 400:
        raise LLMRequestError(f"OpenRouter error {response.status_code}: {response.text[:300]}")
    return response.json()


async def call_openrouter(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 900,
    temperature: float = 0.4,
) -> str:
    """
    Returns plain text content from the model. Keeps max_tokens modest by
    default — summaries don't need to be long to be useful, and shorter
    completions are kinder to a free-tier budget.
    """
    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    data = await _post_chat_completion(payload)
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as exc:
        raise LLMRequestError(f"Unexpected OpenRouter response shape: {data}") from exc
