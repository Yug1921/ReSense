# Re-sense — AI Research Paper Summarization & Q&A Assistant

Capstone project. Drag-and-drop a research paper (PDF/DOCX) and get:
1. A tone-adaptive summary — **Simple**, **Technical**, or **Connect** — plus basic visualizations/analysis.
2. A precise Q&A chatbot scoped strictly to that one paper's content.

Stack: Next.js 14 (frontend) + FastAPI (backend) + Supabase (Postgres + Storage) + OpenRouter (free-tier LLM).

See `ARCHITECTURE_PRD.md` (from the previous deliverable) for the full architecture, feature spec, and task
breakdown. This repo currently has **Track A (file ingestion & parsing)**, **Track B (tone-based
summarization)**, **Track C (Q&A / context-scoped chat)**, and **Track D (basic visualization/analysis)**
implemented in `backend/`.

## Summary tones

| Tone | Audience | Focus |
|---|---|---|
| `simple` | Layman / first-time reader | Plain language, short sentences, jargon defined inline |
| `technical` | Domain expert / knowledgeable reader | Preserves methodology, terminology, nuance |
| `connect` | Student / practitioner / adjacent field | Real-world relevance — what this means in practice, relatable analogies, how it connects to everyday life, industry, or other fields. Bridges "simple" and "technical" by staying substantive but grounded in application rather than either oversimplifying or drowning in jargon. |

## Backend setup

```bash
cd backend
python -m venv venv && source venv/bin/activate .\venv\Scripts\Activate.ps1    
pip install -r requirements.txt
cp .env.example .env   # fill in SUPABASE_URL, SUPABASE_KEY, OPENROUTER_API_KEY
# run the schema.sql against your Supabase project (SQL editor or psql) before first use
uvicorn app.main:app --reload --port 8000
```

## Endpoints implemented so far

- `POST /upload` — accepts a PDF/DOCX, extracts text + rough structure, stores it, returns `paper_id`.
- `POST /summarize` — given `paper_id` + `tone` (`simple`|`technical`|`connect`), returns a cached or
  freshly-generated summary.
- `POST /ask` — given `paper_id` + `question`, retrieves the most relevant chunks of *that paper only*
  (BM25 keyword retrieval, see `services/retrieval.py`) plus recent chat history, answers from those
  excerpts only, and persists both turns to `chat_messages`.
- `POST /analyze` — given `paper_id`, returns section-length breakdown and keyword frequency (computed,
  no LLM cost) plus a cached paper-type/complexity classification (one small LLM call).
- `GET /health` — basic liveness check.

Not yet built (next tracks): `/session/{id}` aggregate endpoint (Track I), and the entire frontend
(Tracks E–H).
