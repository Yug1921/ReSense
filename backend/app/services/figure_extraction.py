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

MIN_WIDTH = 120
MIN_HEIGHT = 120
MAX_IMAGES_PER_PAPER = 12  # hard cap so one dense paper can't blow the vision budget


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
    finally:
        doc.close()

    return images