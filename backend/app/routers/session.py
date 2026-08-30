"""
Track I — GET /session/{paper_id}

The single endpoint the frontend calls on page load / reload to
restore a paper's full state: paper metadata, every summary tone
already generated, cached analysis (if any), and full chat history.
This is what makes "refresh the browser mid-session" safe — the
frontend never has to hold state that only lives in memory.

Read-only: never triggers a new LLM call. If a tone hasn't been
summarized yet, or /analyze hasn't been run yet, those fields just
come back empty/None and the frontend calls the respective endpoint
on demand.
"""
from fastapi import APIRouter, HTTPException

from app.db.supabase_client import (
    get_supabase,
    PAPERS_TABLE,
    SUMMARIES_TABLE,
    ANALYSIS_TABLE,
    CHAT_MESSAGES_TABLE,
)
from app.models.schemas import (
    SessionResponse,
    PaperInfo,
    AnalyzeResponse,
    Classification,
    ChatTurn,
)

router = APIRouter(tags=["session"])


@router.get("/session/{paper_id}", response_model=SessionResponse)
async def get_session(paper_id: str) -> SessionResponse:
    supabase = get_supabase()

    paper_result = supabase.table(PAPERS_TABLE).select("*").eq("id", paper_id).limit(1).execute()
    if not paper_result.data:
        raise HTTPException(status_code=404, detail="No paper found for this paper_id.")
    paper = paper_result.data[0]

    summaries_result = (
        supabase.table(SUMMARIES_TABLE).select("tone, content").eq("paper_id", paper_id).execute()
    )
    summaries = {row["tone"]: row["content"] for row in summaries_result.data}

    analysis_result = (
        supabase.table(ANALYSIS_TABLE).select("*").eq("paper_id", paper_id).limit(1).execute()
    )
    analysis = None
    if analysis_result.data:
        data = analysis_result.data[0]["chart_data_json"]
        classification = data.get("classification")
        analysis = AnalyzeResponse(
            paper_id=paper_id,
            section_lengths=data["section_lengths"],
            keywords=data["keywords"],
            classification=Classification(**classification) if classification else None,
            cached=True,
        )

    chat_result = (
        supabase.table(CHAT_MESSAGES_TABLE)
        .select("role, content")
        .eq("paper_id", paper_id)
        .order("created_at")
        .execute()
    )
    chat_history = [ChatTurn(**row) for row in chat_result.data]

    return SessionResponse(
        paper=PaperInfo(
            paper_id=paper["id"],
            filename=paper["filename"],
            status=paper["status"],
            structure=paper.get("structure_json") or {},
        ),
        summaries=summaries,
        analysis=analysis,
        chat_history=chat_history,
    )