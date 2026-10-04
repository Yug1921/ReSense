"""
Track J (Vision) — extracts embedded images from a PDF's pages.

Only PDF is supported for now — reliably pulling embedded images out of
DOCX requires unzipping the OOXML package and matching relationship IDs,
which is a reasonable follow-up but out of scope for the first pass.

Small images (icons, logos, decorative rules) are filtered out by a
minimum-dimension heuristic, since captioning those with a vision model
would waste free-tier budget on content that was never a real figure.   
"""
import pymupdf
import re

MIN_WIDTH = 120
MIN_HEIGHT = 120
MAX_IMAGES_PER_PAPER = 32  # bound vision work while covering dense survey papers
CAPTION_REGION_HEIGHT = 360
_VISUAL_CAPTION_RE = re.compile(
    r"^\s*(?P<label>(?:figure|fig\.?|table)\s*\d+[a-z]?)\b(?P<title>.*)$",
    re.IGNORECASE,
)


class ImageExtractionError(Exception):
    pass


def extract_images_from_pdf(file_bytes: bytes) -> list[dict]:
    """
    Returns a list of dicts, each: {page_number, image_bytes, extension, width, height}.
    Ordered by page number, capped at MAX_IMAGES_PER_PAPER.
    """
    try:
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise ImageExtractionError(f"Could not open PDF for image extraction: {exc}") from exc

    images: list[dict] = []
    try:
        for page_index in range(len(doc)):
            if len(images) >= MAX_IMAGES_PER_PAPER:
                break
            page = doc[page_index]
            seen_xrefs_this_page: set[int] = set()
            for img in page.get_images(full=True):
                xref = img[0]
                if xref in seen_xrefs_this_page:
                    continue  # the same image can be referenced more than once per page
                seen_xrefs_this_page.add(xref)

                base_image = doc.extract_image(xref)
                width = base_image.get("width", 0)
                height = base_image.get("height", 0)
                if width < MIN_WIDTH or height < MIN_HEIGHT:
                    continue  # skip icons/logos/decorative rules

                images.append(
                    {
                        "page_number": page_index + 1,
                        "image_bytes": base_image["image"],
                        "extension": base_image["ext"],
                        "width": width,
                        "height": height,
                    }
                )
                if len(images) >= MAX_IMAGES_PER_PAPER:
                    break

            if len(images) >= MAX_IMAGES_PER_PAPER:
                break

            # Charts and tables are often vector drawing commands rather than
            # embedded images. Render a bounded region around their printed
            # caption so vision receives those visuals too.
            for block in page.get_text("blocks"):
                block_text = " ".join(block[4].split())
                caption_match = _VISUAL_CAPTION_RE.match(block_text)
                if not caption_match:
                    continue

                label = caption_match.group("label").lower()
                caption_y0, caption_y1 = block[1], block[3]
                if label.startswith("table"):
                    clip_top = max(0, caption_y0 - 20)
                    clip_bottom = min(page.rect.height, caption_y1 + CAPTION_REGION_HEIGHT)
                else:
                    clip_top = max(0, caption_y0 - CAPTION_REGION_HEIGHT)
                    clip_bottom = min(page.rect.height, caption_y1 + 20)

                clip = pymupdf.Rect(0, clip_top, page.rect.width, clip_bottom)
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=clip, alpha=False)
                images.append(
                    {
                        "page_number": page_index + 1,
                        "image_bytes": pixmap.tobytes("png"),
                        "extension": "png",
                        "width": pixmap.width,
                        "height": pixmap.height,
                    }
                )
                if len(images) >= MAX_IMAGES_PER_PAPER:
                    break
    finally:
        doc.close()

    return images