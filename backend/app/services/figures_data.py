"""Shared helper for loading and captioning every figure for a paper."""

import re


_CAPTION_RE = re.compile(
    r"(?P<label>\b(?:figure|fig\.?|table)\s*\d+[a-z]?)\s*[:.\-]?\s*"
    r"(?P<title>.*?)(?=\s+(?:figure|fig\.?|table)\s*\d+[a-z]?\b|$)",
    re.IGNORECASE,
)


def _caption_fallback(paper_id: str, raw_text: str) -> list[dict]:
    """Build visual records from printed captions when image bytes are absent."""
    rows: list[dict] = []
    seen_labels: set[str] = set()
    for line in raw_text.splitlines():
        for match in _CAPTION_RE.finditer(line):
            label = match.group("label").strip()
            title = match.group("title").strip(" .:-")
            if not title:
                continue
            normalized_label = label.lower().replace(" ", "")
            if normalized_label in seen_labels:
                continue
            seen_labels.add(normalized_label)
            image_type = "table" if label.lower().startswith("table") else "other"
            rows.append(
                {
                    "id": f"caption-{paper_id}-{len(rows)}",
                    "paper_id": paper_id,
                    "page_number": 0,
                    "storage_path": "",
                    "image_type": image_type,
                    "caption": f"{label} {title}",
                    "width": 0,
                    "height": 0,
                }
            )
    return rows


async def ensure_figures_captioned(supabase, FIGURES_TABLE, paper_id: str) -> list[dict]:
    """Caption uncached figures on demand and return all captioned figures."""
    from app.services.figure_storage import download_figure_image
    from app.services.vision import call_vision_model
    from app.services.vision_prompts import build_vision_prompt, parse_vision_response

    figures_result = (
        supabase.table(FIGURES_TABLE)
        .select("*")
        .eq("paper_id", paper_id)
        .order("page_number")
        .execute()
    )
    rows = figures_result.data

    for row in rows:
        if row.get("caption"):
            continue
        try:
            image_bytes = download_figure_image(row["storage_path"])
            extension = row["storage_path"].rsplit(".", 1)[-1]
            system_prompt, user_text = build_vision_prompt(row["page_number"])
            raw_response = await call_vision_model(system_prompt, user_text, image_bytes, extension)
            image_type, caption = parse_vision_response(raw_response)
            supabase.table(FIGURES_TABLE).update(
                {"image_type": image_type, "caption": caption}
            ).eq("id", row["id"]).execute()
            row["image_type"] = image_type
            row["caption"] = caption
        except Exception:
            continue

    captioned_rows = [row for row in rows if row.get("caption")]
    if captioned_rows:
        return captioned_rows

    # Older uploads may have no figure rows because vector visuals were not
    # extracted. Captions still provide a reliable inventory and anchor the
    # model to the correct visual names and nearby paper discussion.
    paper_result = (
        supabase.table("papers")
        .select("raw_text")
        .eq("id", paper_id)
        .limit(1)
        .execute()
    )
    raw_text = paper_result.data[0].get("raw_text") if paper_result.data else ""
    return _caption_fallback(paper_id, raw_text or "")