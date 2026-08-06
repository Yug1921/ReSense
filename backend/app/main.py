"""
Re-sense backend entry point.

Currently wires up Track A (upload), Track B (summarize), Track C
(ask), and Track D (analyze). Track I's /session/{id} aggregate
endpoint gets added the same way — a new router module + one line here.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import upload, summarize, ask, analyze

app = FastAPI(title="Re-sense API", version="0.1.0")

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


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok"}
