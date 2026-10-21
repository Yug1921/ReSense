"""
Check which free AI models your keys can use right now.

Run from the backend folder:  python -m app.check_ai

For each provider with a key in .env it lists the models ReSense would try,
in order, and sends each a tiny test message. Nothing is saved.
"""
import asyncio

from app.config import settings
from app.services import llm, providers


async def _check() -> None:
    providers.reset()
    keys = {
        "Gemini": settings.gemini_api_key,
        "Groq": settings.groq_api_key,
        "OpenRouter": settings.openrouter_api_key,
    }
    for name, key in keys.items():
        print(f"{name:<11} key {'found' if key else 'MISSING (add it to backend/.env)'}")
    print()

    candidates = await providers.candidates(estimated_tokens=0)
    for provider, error in providers.discovery_errors().items():
        print(f"Couldn't get {provider}'s model list ({error}). Trying common model names instead.")
    if not candidates:
        print("No models to try. Add at least one key to backend/.env.")
        return

    working = 0
    for candidate in candidates:
        payload = {
            "model": candidate.model,
            "messages": [{"role": "user", "content": "Reply with the single word OK."}],
            "max_tokens": 200,
            **providers.request_options(candidate),
        }
        try:
            data = await llm._post_chat_completion(payload, candidate.base_url, candidate.api_key)
            reply = (data["choices"][0]["message"]["content"] or "").strip()
            status = f"works (replied: {reply[:30]!r})" if reply else "answered, but empty"
            working += bool(reply)
        except Exception as exc:  # report every failure, keep checking the rest
            status = f"FAILED: {str(exc)[:160]}"
        print(f"{candidate.provider:<11} {candidate.model:<45} {status}")

    print(f"\n{working} of {len(candidates)} models answered.")
    if working == 0:
        print("Nothing answered: check the keys, or the free limits may be used up for today.")


if __name__ == "__main__":
    asyncio.run(_check())
