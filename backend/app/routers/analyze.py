"""
Track D — POST /analyze

Returns chart-ready JSON only — no chart rendering here, that's Track
G's job on the frontend. Section-length and keyword-frequency are
computed for free (no LLM call); classification uses one small cached
LLM call.
"""
from fastapi import APIRouter, HTTPException

from app.db.supabase_client import get_supabase, PAPERS_TABLE, ANALYSIS_TABLE
from app.models.schemas import AnalyzeRequest, AnalyzeResponse, Classification
from app.services.analysis import (
    section_length_stats,
    keyword_frequency,
    structure_score,
    deterministic_complexity_score,
    classify_paper,
)


router = APIRouter(tags=["analyze"])


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_paper(req: AnalyzeRequest) -> AnalyzeResponse:
    supabase = get_supabase()

    paper_result = (
        supabase.table(PAPERS_TABLE).select("*").eq("id", req.paper_id).limit(1).execute()
    )
    if not paper_result.data:
        raise HTTPException(status_code=404, detail="No paper found for this paper_id.")
    paper = paper_result.data[0]

    if paper["status"] != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Paper is not ready for analysis (status: {paper['status']}).",
        )

    cached = (
        supabase.table(ANALYSIS_TABLE).select("*").eq("paper_id", req.paper_id).limit(1).execute()
    )
    if cached.data:
        data = cached.data[0]["chart_data_json"]
        if data.get("version") != 3:
            cached = None
        else:
            return AnalyzeResponse(
                paper_id=req.paper_id,
                section_lengths=data["section_lengths"],
                keywords=data["keywords"],
                structure_score=data["structure_score"],
                classification=data.get("classification"),
                cached=True,
            )

    section_lengths = section_length_stats(paper.get("structure_json"), paper["raw_text"])
    keywords = keyword_frequency(paper["raw_text"])
    paper_structure_score = structure_score(section_lengths)
    classification = await classify_paper(paper["raw_text"])  # may be None on LLM failure
    score = deterministic_complexity_score(paper["raw_text"], section_lengths)
    complexity = next(label for ceiling, label in ((2, "low"), (4, "medium-low"), (6, "medium"), (8, "high"), (10, "very high")) if score <= ceiling)
    classification = classification or {"paper_type": "research paper"}
    classification.update({"complexity": complexity, "complexity_score": score})

    chart_data_json = {
        "version": 3,
        "section_lengths": section_lengths,
        "keywords": keywords,
        "structure_score": paper_structure_score,
        "classification": classification,
    }
    supabase.table(ANALYSIS_TABLE).upsert(
        {"paper_id": req.paper_id, "chart_data_json": chart_data_json},
        on_conflict="paper_id",
    ).execute()

    return AnalyzeResponse(
        paper_id=req.paper_id,
        section_lengths=section_lengths,
        keywords=keywords,
        structure_score=paper_structure_score,
        classification=Classification(**classification) if classification else None,
        cached=False,
    )
