"""
Re-sense backend entry point.

Currently wires up Track A (upload), Track B (summarize), Track C
(ask), and Track D (analyze). Track I's /session/{id} aggregate
endpoint gets added the same way — a new router module + one line here.
"""
from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import upload, summarize, ask, analyze, session, figures

app = FastAPI(title="Re-sense API", version="0.1.0")

@app.middleware("http")
async def catch_unhandled_exceptions(request: Request, call_next):
    """
    Registered BEFORE CORSMiddleware below — that ordering matters. Starlette
    wraps middleware such that whatever is added first ends up innermost
    (closer to the router) among user middleware, and a plain
    `@app.exception_handler(Exception)` is special-cased by Starlette to
    attach to ServerErrorMiddleware, which sits OUTSIDE CORSMiddleware
    entirely. Catching the exception here — inside a real HTTP middleware
    positioned inside CORS — means the JSONResponse we return still passes
    back out through CORSMiddleware, so it gets proper CORS headers.
    """
    try:
        return await call_next(request)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Unexpected server error: {exc}"},
        )

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(summarize.router)
app.include_router(ask.router)
app.include_router(analyze.router)
app.include_router(session.router)
app.include_router(figures.router)


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok"}
