"""
Which free AI models to try, and in what order.

Free model names change often (models are renamed, retired, or lose their
free tier), so instead of a fixed list we ask each provider which models
your key can use right now and pick from a ranked wish list. The result is
cached for a few hours. Models that just hit a limit are rested for a while
so the next request goes straight to one that works.

Order: Gemini first (best quality, 1M-token context, the most free requests
a day), then Groq (very fast, but its free plan only fits short requests),
then OpenRouter's free models (fewest free requests a day).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import httpx

from app.config import settings

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

_DISCOVERY_TTL = 6 * 3600
_DISCOVERY_TIMEOUT = 10.0

# Most models per provider to try for one request, so a bad day can't make
# a single request wait through a dozen failures.
_MAX_PER_PROVIDER = 3

# Groq's free plan allows about 8,000 tokens per minute per model, counting
# the prompt and the reply together. Bigger requests are refused outright.
GROQ_MAX_REQUEST_TOKENS = 7500


@dataclass(frozen=True)
class Candidate:
    provider: str  # gemini | groq | openrouter
    model: str
    base_url: str
    api_key: str

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"


# --------------------------------------------------------------------------
# Ranking: which of a provider's models we want, best first.
# --------------------------------------------------------------------------

_GEMINI_SKIP = ("pro", "image", "tts", "audio", "live", "embedding", "vision", "thinking", "exp", "learnlm", "8b")


def _version(model_id: str) -> tuple[float, ...]:
    numbers = re.findall(r"\d+(?:\.\d+)?", model_id)
    return tuple(float(n) for n in numbers[:2]) or (0.0,)


def rank_gemini(model_ids: list[str]) -> list[str]:
    """Newest Flash first, stable before preview, Flash-Lite last.

    Pro models left the free tier, so they are never picked.
    """
    usable = []
    for model_id in model_ids:
        name = model_id.removeprefix("models/")
        if not name.startswith("gemini-") or "flash" not in name:
            continue
        if any(word in name for word in _GEMINI_SKIP):
            continue
        usable.append(name)

    def score(name: str):
        lite = "lite" in name
        preview = "preview" in name or re.search(r"-\d{2}-\d{2}$", name) is not None
        return (lite, preview, tuple(-v for v in _version(name)), name)

    return sorted(dict.fromkeys(usable), key=score)


# Groq: strongest general models first. Matched by prefix so new point
# releases (qwen3.8 -> qwen3.9) are picked up without a code change.
_GROQ_PREFERENCE = (
    "openai/gpt-oss-120b",
    "qwen/qwen3",
    "llama-3.3-70b",
    "meta-llama/llama-4",
    "openai/gpt-oss-20b",
    "llama-3.1-8b",
)
_GROQ_SKIP = ("whisper", "tts", "guard", "safeguard", "compound", "playai", "orpheus", "prompt-guard")


def rank_groq(model_ids: list[str]) -> list[str]:
    ranked: list[str] = []
    for prefix in _GROQ_PREFERENCE:
        matches = [m for m in model_ids if m.startswith(prefix) and not any(s in m for s in _GROQ_SKIP)]
        ranked.extend(sorted(matches, key=lambda m: tuple(-v for v in _version(m))))
    return list(dict.fromkeys(ranked))


# OpenRouter: only models that are free right now, with room for a whole
# paper. Families known to write well come first; any other free model with
# a long context is kept as a last resort.
_OPENROUTER_PREFERENCE = (
    "nvidia/nemotron",
    "google/gemma",
    "thinkingmachines/inkling",
    "qwen/",
    "deepseek/",
    "meta-llama/",
    "mistralai/",
)
_OPENROUTER_MIN_CONTEXT = 32_000


def rank_openrouter(models: list[dict]) -> list[str]:
    free = []
    for model in models:
        model_id = model.get("id", "")
        pricing = model.get("pricing") or {}
        is_free = model_id.endswith(":free") or (
            str(pricing.get("prompt")) in ("0", "0.0") and str(pricing.get("completion")) in ("0", "0.0")
        )
        if not is_free or model_id.startswith("openrouter/"):
            continue
        if (model.get("context_length") or 0) < _OPENROUTER_MIN_CONTEXT:
            continue
        modality = (model.get("architecture") or {}).get("output_modalities") or ["text"]
        if "text" not in modality:
            continue
        free.append(model_id)

    def score(model_id: str):
        for rank, prefix in enumerate(_OPENROUTER_PREFERENCE):
            if model_id.startswith(prefix):
                return (rank, tuple(-v for v in _version(model_id)))
        return (len(_OPENROUTER_PREFERENCE), ())

    return sorted(free, key=score)


# --------------------------------------------------------------------------
# Discovery (cached) and resting models that just failed.
# --------------------------------------------------------------------------

# Used only when a provider can't be asked for its model list (network
# trouble, or a key that is wrong): long-lived model names worth a try.
_FALLBACK_MODELS = {
    "gemini": ["gemini-2.5-flash", "gemini-2.5-flash-lite"],
    "groq": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
    "openrouter": [],
}


@dataclass
class _State:
    discovered: dict[str, tuple[float, list[str]]] = field(default_factory=dict)
    resting_until: dict[str, float] = field(default_factory=dict)
    discovery_errors: dict[str, str] = field(default_factory=dict)


_state = _State()


async def _list_models(provider: str, api_key: str) -> list[str]:
    async with httpx.AsyncClient(timeout=_DISCOVERY_TIMEOUT) as client:
        if provider == "gemini":
            response = await client.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": api_key, "pageSize": 1000},
            )
            response.raise_for_status()
            models = [
                m["name"]
                for m in response.json().get("models", [])
                if "generateContent" in (m.get("supportedGenerationMethods") or [])
            ]
            return rank_gemini(models)
        if provider == "groq":
            response = await client.get(
                f"{GROQ_BASE_URL}/models", headers={"Authorization": f"Bearer {api_key}"}
            )
            response.raise_for_status()
            models = [m["id"] for m in response.json().get("data", []) if m.get("active", True)]
            return rank_groq(models)
        response = await client.get(
            f"{settings.openrouter_base_url}/models", headers={"Authorization": f"Bearer {api_key}"}
        )
        response.raise_for_status()
        return rank_openrouter(response.json().get("data", []))


async def _models_for(provider: str, api_key: str, pinned: list[str]) -> list[str]:
    """Pinned models from .env first, then the best discovered ones."""
    now = time.monotonic()
    cached = _state.discovered.get(provider)
    if cached and cached[0] > now:
        discovered = cached[1]
    else:
        try:
            discovered = await _list_models(provider, api_key)
            _state.discovered[provider] = (now + _DISCOVERY_TTL, discovered)
            _state.discovery_errors.pop(provider, None)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            # Couldn't ask the provider: try again in a few minutes, and meanwhile
            # use the last list we had, or a few long-lived model names.
            discovered = cached[1] if cached and cached[1] else _FALLBACK_MODELS[provider]
            _state.discovered[provider] = (now + 300, discovered)
            _state.discovery_errors[provider] = str(exc)[:200]
    return list(dict.fromkeys(pinned + discovered))


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


async def candidates(estimated_tokens: int) -> list[Candidate]:
    """Models to try for one request, best first, skipping any that are resting."""
    plan: list[tuple[str, str, str, list[str]]] = []
    if settings.gemini_api_key:
        plan.append(("gemini", GEMINI_BASE_URL, settings.gemini_api_key, _split(settings.gemini_model)))
    if settings.groq_api_key and estimated_tokens <= GROQ_MAX_REQUEST_TOKENS:
        plan.append(("groq", GROQ_BASE_URL, settings.groq_api_key, _split(settings.groq_model)))
    if settings.openrouter_api_key:
        pinned = _split(settings.openrouter_model) + _split(settings.openrouter_fallback_models)
        plan.append(("openrouter", settings.openrouter_base_url, settings.openrouter_api_key, pinned))

    now = time.monotonic()
    result: list[Candidate] = []
    for provider, base_url, api_key, pinned in plan:
        models = await _models_for(provider, api_key, pinned)
        picked = 0
        for model in models:
            candidate = Candidate(provider, model, base_url, api_key)
            if _state.resting_until.get(candidate.key, 0) > now:
                continue
            result.append(candidate)
            picked += 1
            if picked == _MAX_PER_PROVIDER:
                break
    return result


def rest(candidate: Candidate, seconds: float) -> None:
    """Skip this model for a while (it hit a limit or is gone)."""
    _state.resting_until[candidate.key] = time.monotonic() + seconds


def reset() -> None:
    """Forget discovery and rest periods (used by tests and the check script)."""
    _state.discovered.clear()
    _state.resting_until.clear()
    _state.discovery_errors.clear()


def discovery_errors() -> dict[str, str]:
    """Providers whose model list couldn't be fetched last time, with the reason."""
    return dict(_state.discovery_errors)


def request_options(candidate: Candidate) -> dict:
    """Per-model extras: keep thinking short where the model supports it.

    Sending a reasoning setting a model doesn't support gets the request
    refused, so this only adds it where it is known to work.
    """
    if candidate.provider == "gemini":
        return {"reasoning_effort": "low"}
    if candidate.provider == "groq":
        if "gpt-oss" in candidate.model:
            return {"reasoning_effort": "low"}
        if candidate.model.startswith("qwen/"):
            return {"reasoning_effort": "none"}
        return {}
    return {"reasoning": {"effort": "low", "exclude": True}}
