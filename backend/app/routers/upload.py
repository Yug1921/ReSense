"""
Track A — POST /upload

Accepts a PDF/DOCX, validates it, parses text + structure exactly once,
dedupes on file hash, and persists everything to Supabase keyed by a
new paper_id. Every other feature reads from this cached row and never
re-touches the raw file.
"""
from fastapi import APIRouter, HTTPException, UploadFile, File

from app.config import settings
from app.db.supabase_client import get_supabase, PAPERS_TABLE, FIGURES_TABLE
from app.models.schemas import UploadResponse
from app.services.parser import (
    parse_file,
    compute_file_hash,
    UnsupportedFileTypeError,
    FileParsingError,
)
from app.services.figure_extraction import extract_images_from_pdf, ImageExtractionError
from app.services.figure_storage import upload_figure_image

router = APIRouter(tags=["upload"])

_ALLOWED_EXTENSIONS = (".pdf", ".docx", ".doc")


@router.post("/upload", response_model=UploadResponse)
async def upload_paper(file: UploadFile = File(...)) -> UploadResponse:
    filename = file.filename or "uploaded_file"

    if not filename.lower().endswith(_ALLOWED_EXTENSIONS):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(_ALLOWED_EXTENSIONS)}",
        )

    file_bytes = await file.read()
    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > settings.max_upload_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size_mb:.1f}MB). Max is {settings.max_upload_mb}MB.",
        )
    if size_mb == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    file_hash = compute_file_hash(file_bytes)
    supabase = get_supabase()

    # Dedup: reuse the existing paper_id instead of reprocessing (see
    # reliability checklist — "duplicate upload of the same file").
    existing = (
        supabase.table(PAPERS_TABLE).select("*").eq("file_hash", file_hash).limit(1).execute()
    )
    if existing.data:
        row = existing.data[0]
        return UploadResponse(
            paper_id=row["id"],
            status=row["status"],
            filename=row["filename"],
            structure=row.get("structure_json") or {},
            reused_existing=True,
            message="This file was already uploaded — reusing the existing session.",
        )

    try:
        parsed = parse_file(filename, file_bytes)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileParsingError as exc:
        # Corrupted / unreadable file — insert a parse_failed row so the
        # frontend can show a clear error state rather than a generic 500.
        insert_result = (
            supabase.table(PAPERS_TABLE)
            .insert(
                {
                    "filename": filename,
                    "file_hash": file_hash,
                    "status": "parse_failed",
                }
            )
            .execute()
        )
        row = insert_result.data[0]
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not read this file — it may be corrupted. "
                f"(paper_id={row['id']} saved as parse_failed)"
            ),
        ) from exc

    insert_result = (
        supabase.table(PAPERS_TABLE)
        .insert(
            {
                "filename": filename,
                "file_hash": file_hash,
                "raw_text": parsed.raw_text,
                "structure_json": parsed.structure,
                "status": parsed.status,
            }
        )
        .execute()
    )
    row = insert_result.data[0]
    if parsed.status == "ready" and filename.lower().endswith(".pdf"):
                _extract_and_store_figures(supabase, paper_id=row["id"], file_bytes=file_bytes)
    message = None
    if parsed.status == "empty_text":
        message = (
            "Couldn't extract readable text from this file — it may be a "
            "scanned or image-only document. Try a text-based PDF/DOCX instead."
        )

    return UploadResponse(
        paper_id=row["id"],
        status=parsed.status,
        filename=filename,
        structure=parsed.structure,
        message=message,
    )

def _extract_and_store_figures(supabase, paper_id: str, file_bytes: bytes) -> None:
    """
    Pulls embedded images out of the PDF and stores them (bytes only —
    no captioning here, that's the vision model's job in /figures,
    called on demand so uploading never costs a vision-model call).
    Never raises: figure extraction is a bonus feature and must not
    block a successful upload if it fails for any reason (e.g. the
    Storage bucket isn't set up yet).
    """
    try:
        images = extract_images_from_pdf(file_bytes)
    except ImageExtractionError:
        return

    for index, img in enumerate(images):
        try:
            storage_path = upload_figure_image(
                paper_id, img["page_number"], index, img["image_bytes"], img["extension"]
            )
            supabase.table(FIGURES_TABLE).insert(
                {
                    "paper_id": paper_id,
                    "page_number": img["page_number"],
                    "storage_path": storage_path,
                    "width": img["width"],
                    "height": img["height"],
                }
            ).execute()
        except Exception:
            continue  # one bad image shouldn't sink the rest