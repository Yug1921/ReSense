import unittest

from app.services.parser import _extract_page_text_in_reading_order
from app.services.references import extract_references


class _FakePage:
    def __init__(self, lines, width=600):
        self.rect = type("Rect", (), {"width": width})()
        self._lines = lines

    def get_text(self, kind):
        if kind != "dict":
            return {"blocks": []}
        return {
            "blocks": [
                {
                    "lines": [
                        {
                            "bbox": [x0, y0, x1, y1],
                            "spans": [{"text": text}],
                        }
                        for x0, y0, x1, y1, text in self._lines
                    ]
                }
            ]
        }


class ParserTests(unittest.TestCase):
    def test_single_column_preserves_vertical_order(self):
        page = _FakePage(
            [
                (50, 20, 550, 30, "References"),
                (50, 40, 550, 50, "[1] First reference"),
                (50, 60, 550, 70, "[2] Second reference"),
            ]
        )
        self.assertEqual(
            _extract_page_text_in_reading_order(page).splitlines(),
            ["References", "[1] First reference", "[2] Second reference"],
        )

    def test_two_columns_read_left_then_right(self):
        lines = []
        for number, y in enumerate((40, 60, 80), 1):
            lines.append((45, y, 275, y + 10, f"[{number}] Left reference"))
            lines.append((325, y, 555, y + 10, f"[{number + 3}] Right reference"))
        page = _FakePage(lines)
        self.assertEqual(
            _extract_page_text_in_reading_order(page).splitlines(),
            [
                "[1] Left reference",
                "[2] Left reference",
                "[3] Left reference",
                "[4] Right reference",
                "[5] Right reference",
                "[6] Right reference",
            ],
        )

    def test_full_width_heading_precedes_columns(self):
        page = _FakePage(
            [
                (40, 10, 560, 20, "REFERENCES"),
                (45, 40, 275, 50, "[1] Left reference"),
                (325, 40, 555, 50, "[3] Right reference"),
                (45, 60, 275, 70, "[2] Left reference"),
                (325, 60, 555, 70, "[4] Right reference"),
            ]
        )
        self.assertEqual(
            _extract_page_text_in_reading_order(page).splitlines()[0],
            "REFERENCES",
        )

    def test_same_baseline_fragments_merge_without_crossing_columns(self):
        page = _FakePage(
            [
                (45, 40, 150, 50, "A citation"),
                (155, 40.5, 275, 50.5, "continues here."),
                (325, 40, 430, 50, "Right citation"),
                (435, 40.5, 555, 50.5, "continues here."),
            ]
        )
        self.assertEqual(
            _extract_page_text_in_reading_order(page).splitlines(),
            ["A citation continues here.", "Right citation continues here."],
        )

    def test_centered_unique_footer_is_removed(self):
        page = _FakePage(
            [
                (50, 40, 275, 50, "[1] A complete reference record."),
                (295, 733, 317, 745, "9 778"),
            ]
        )
        self.assertEqual(
            _extract_page_text_in_reading_order(page).splitlines(),
            ["[1] A complete reference record."],
        )

    def test_plain_numbered_and_hyphenated_references_are_joined(self):
        text = (
            "1 Author, A. A paper with a long inter-\n"
            "pretation title and venue information.\n\n"
            "2 Author, B. Another sufficiently long reference title and venue."
        )
        references = extract_references({"sections": {"References": text}}, text)
        self.assertEqual(len(references), 2)
        self.assertIn("interpretation", references[0])
        self.assertNotIn("inter- pretation", references[0])

    def test_ten_references_keep_column_sequence_after_extraction(self):
        text = "\n".join(
            f"[{index}] Author {index}. A sufficiently long reference title and venue."
            for index in range(1, 11)
        )
        references = extract_references({"sections": {"References": text}}, text)
        self.assertEqual(len(references), 10)
        self.assertEqual([reference.split("]", 1)[0] for reference in references], [
            f"[{index}" for index in range(1, 11)
        ])
