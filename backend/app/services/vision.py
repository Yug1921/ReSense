"""
Track J (Vision) — calls a vision-capable OpenRouter model on one image.

Deliberately separate from llm.py's call_openrouter: most of your text
models (Nemotron 3 Super, Ling-3.0-flash, gpt-oss-20b) cannot see images
at all, so vision calls need their own model chain
(OPENROUTER_VISION_MODEL + OPENROUTER_VISION_FALLBACK_MODELS) rather
than reusing the text chain. The actual HTTP call is shared via
_post_chat_completion from llm.py — only the payload shape and the
model chain differ.
"""
import base64

from app.config import settings
from app.services.llm import _post_chat_completion, LLMRequestError

_EXTENSION_TO_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}


async def call_vision_model(
    system_prompt: str,
    user_text: str,
    image_bytes: bytes,
    extension: str,
    max_tokens: int = 500,
) -> str:
    mime_type = _EXTENSION_TO_MIME.get(extension.lower(), "image/png")
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime_type};base64,{b64}"

    payload_base = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }

    last_error: Exception | None = None
    for model in settings.openrouter_vision_models_chain:
        try:
            data = await _post_chat_completion({**payload_base, "model": model})
            content = data["choices"][0]["message"]["content"]
            if not content:
                raise LLMRequestError(f"Vision model '{model}' returned empty content.")
            return content.strip()
        except (LLMRequestError, KeyError, IndexError, AttributeError, TypeError) as exc:
            last_error = exc
            continue

    raise LLMRequestError(
        f"All configured vision models failed. Last error: {last_error}"
    ) from last_error