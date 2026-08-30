"""
Track J (Vision) — prompt for describing one extracted image.

One combined prompt does classification (what kind of image is this)
and description in a single vision-model call, rather than two separate
calls — this matters for free-tier budget, since every extra call is
extra usage against a rate limit.
"""

_VISION_SYSTEM_PROMPT = (
    "You are looking at one image extracted from a research paper. "
    "First, on its own line, identify what kind of image this is using "
    "exactly one of these words: chart, diagram, table, code, photo, other. "
    "Then, on the following lines, describe it precisely:\n"
    "- If it's a CHART or DIAGRAM: describe what it shows, the trend or "
    "relationship, and any axis labels or key values that are visible.\n"
    "- If it's a TABLE: transcribe the column headers and the key rows as "
    "plain text, preserving the actual numbers/values shown — do not "
    "summarize away the specific figures.\n"
    "- If it's CODE: transcribe the code as accurately as you can (in a "
    "code block), then in one sentence explain what it does.\n"
    "- Otherwise: give one neutral sentence describing what's shown.\n"
    "Only describe what is actually visible in the image. Never invent "
    "numbers, labels, or text that isn't really there. Keep the whole "
    "response under 180 words."
)


def build_vision_prompt(page_number: int) -> tuple[str, str]:
    user_text = (
        f"This image was extracted from page {page_number} of a research paper. "
        "Classify and describe it as instructed."
    )
    return _VISION_SYSTEM_PROMPT, user_text


def parse_vision_response(raw_response: str) -> tuple[str, str]:
    """
    Splits the model's response into (image_type, description).
    The first line is expected to be the single classification word;
    everything after is the description. Falls back to "other" and the
    full response if the model didn't follow the format exactly.
    """
    lines = raw_response.strip().split("\n", 1)
    first_line = lines[0].strip().lower()
    valid_types = {"chart", "diagram", "table", "code", "photo", "other"}

    if first_line in valid_types and len(lines) > 1:
        return first_line, lines[1].strip()
    return "other", raw_response.strip()