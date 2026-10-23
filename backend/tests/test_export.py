import io
import unittest
import zipfile

import pymupdf

from app.services.export import download_name, parse_blocks, summary_docx, summary_pdf

SUMMARY = """**1. Research problem**
Deeper networks train *worse*.

## Contributions
- Residual **blocks** learn F(x) = H(x) − x
- Identity shortcuts

1. The first point is short.
2. The second point is here.
It continues.
"""


class ExportTests(unittest.TestCase):
    def test_blocks_follow_the_app_reader(self):
        kinds = [(b.kind, b.text or b.items) for b in parse_blocks(SUMMARY)]
        self.assertEqual(kinds[0], ("heading", "Research problem"))
        self.assertEqual(kinds[2], ("heading", "Contributions"))
        self.assertEqual(kinds[4][1], ["The first point is short.", "The second point is here. It continues."])

    def test_pdf_flows_over_pages_and_keeps_every_word(self):
        long = SUMMARY + "\n\n" + "\n\n".join(f"Paragraph {i} about residual learning." for i in range(400))
        document = pymupdf.open("pdf", summary_pdf("my_paper.pdf", "technical", long))
        self.assertGreater(document.page_count, 1)
        text = "".join(page.get_text() for page in document)
        self.assertIn("Paragraph 399", text)
        self.assertIn("Page 1 of", text)
        self.assertNotIn("**", text)

    def test_word_file_has_headings_and_lists(self):
        data = summary_docx("my_paper.pdf", "academic", SUMMARY)
        xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
        self.assertIn("Research problem", xml)
        self.assertIn("ListBullet", xml)
        self.assertNotIn("**", xml)

    def test_download_name(self):
        self.assertEqual(download_name("My Paper (1).pdf", "research_insight", "pdf"), "My-Paper-1-research-insight.pdf")
