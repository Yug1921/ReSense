"""
Track J (Vision) — Supabase Storage plumbing for extracted figure images.

Kept separate from figure_extraction.py (which only deals with bytes in
memory) so both upload.py and figures.py can share the same upload/
download logic instead of duplicating storage calls.
"""
from app.db.supabase_client import get_supabase, FIGURES_BUCKET

_EXT_TO_CONTENT_TYPE = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


def upload_figure_image(paper_id: str, page_number: int, index: int, image_bytes: bytes, extension: str) -> str:
    """Uploads one extracted image to Supabase Storage; returns its storage path."""
    supabase = get_supabase()
    path = f"{paper_id}/page{page_number}_{index}.{extension}"
    content_type = _EXT_TO_CONTENT_TYPE.get(extension.lower(), "application/octet-stream")
    supabase.storage.from_(FIGURES_BUCKET).upload(
        path, image_bytes, {"content-type": content_type, "upsert": "true"}
    )
    return path


def download_figure_image(storage_path: str) -> bytes:
    supabase = get_supabase()
    return supabase.storage.from_(FIGURES_BUCKET).download(storage_path)