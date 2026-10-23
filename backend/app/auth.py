"""
Who is calling: every paper endpoint requires a signed-in Supabase user.

The frontend signs in with Supabase Auth and sends its access token as
`Authorization: Bearer <token>`. We ask Supabase who the token belongs to
(GET /auth/v1/user) instead of checking the signature ourselves, so this works
with both the legacy JWT secret and the newer signing keys, and needs no extra
secret in .env. Answers are cached briefly so a page load that fires several
requests costs one lookup, not one per request.
"""
import time
from dataclasses import dataclass

import httpx
from fastapi import Header, HTTPException

from app.config import settings

_CACHE_SECONDS = 60
_CACHE_MAX = 1000
_token_cache: dict[str, tuple[float, "CurrentUser"]] = {}


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None = None


def _unauthorized(detail: str = "Please sign in to continue.") -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


async def _lookup_user(token: str) -> CurrentUser:
    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/user"
    headers = {"apikey": settings.supabase_key, "Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Sign-in service is unreachable. Try again shortly.") from exc
    if response.status_code in (401, 403):
        raise _unauthorized("Your sign-in has expired. Please sign in again.")
    if response.status_code != 200:
        raise HTTPException(status_code=503, detail="Sign-in service is unavailable. Try again shortly.")
    data = response.json()
    if not data.get("id"):
        raise _unauthorized()
    return CurrentUser(id=data["id"], email=data.get("email"))


async def current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    """FastAPI dependency: the signed-in user, or 401."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauthorized()
    token = authorization[7:].strip()
    if not token:
        raise _unauthorized()

    now = time.monotonic()
    cached = _token_cache.get(token)
    if cached and cached[0] > now:
        return cached[1]

    user = await _lookup_user(token)
    if len(_token_cache) >= _CACHE_MAX:
        for key, (expires, _) in list(_token_cache.items()):
            if expires <= now:
                del _token_cache[key]
        if len(_token_cache) >= _CACHE_MAX:
            _token_cache.clear()
    _token_cache[token] = (now + _CACHE_SECONDS, user)
    return user
