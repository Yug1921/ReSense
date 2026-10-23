import os
import unittest
from functools import lru_cache
from pathlib import Path

for _name in ("SUPABASE_URL", "SUPABASE_KEY", "OPENROUTER_API_KEY"):
    os.environ.setdefault(_name, "test")

from app.services.analysis import keyword_frequency, section_length_stats
from app.services.parser import parse_file

_PDFS = Path(__file__).resolve().parents[2] / "test-pdfs"


@lru_cache
def _parsed(name: str):
    return parse_file(name, (_PDFS / name).read_bytes())


@unittest.skipUnless(_PDFS.exists(), "test-pdfs folder not available")
class RealPaperOverviewTests(unittest.TestCase):
    def test_resnet_sections_are_its_real_top_level_headings(self):
        paper = _parsed("pdf1_resnet_cvpr2016.pdf")
        stats = section_length_stats(paper.structure, paper.raw_text)
        self.assertEqual(
            [s["label"] for s in stats],
            ["Abstract", "Introduction", "Related Work", "Deep Residual Learning", "Experiments", "References"],
        )
        # The sections account for almost every word of the paper.
        self.assertGreater(sum(s["value"] for s in stats), 0.97 * paper.structure["word_count"])

    def test_bert_skips_table_rows_footnotes_and_subsections(self):
        paper = _parsed("pdf2_bert_naacl2019.pdf")
        labels = [s["label"] for s in section_length_stats(paper.structure, paper.raw_text)]
        self.assertEqual(
            labels,
            ["Abstract", "Introduction", "Related Work", "BERT", "Experiments", "Ablation Studies",
             "Conclusion", "References", "Appendix"],
        )

    def test_key_terms_merge_plurals_and_keep_the_papers_spelling(self):
        resnet = {k["label"]: k["value"] for k in keyword_frequency(_parsed("pdf1_resnet_cvpr2016.pdf").raw_text)}
        self.assertEqual(resnet["layer"], 151)  # 89 x "layer" + 62 x "layers"
        self.assertIn("ImageNet", resnet)
        self.assertNotIn("fig", resnet)
        self.assertFalse(any(label.endswith("-") for label in resnet))

        bert = {k["label"] for k in keyword_frequency(_parsed("pdf2_bert_naacl2019.pdf").raw_text)}
        self.assertIn("fine-tuning", bert)  # PDF ligature restored
        self.assertNotIn("ne-tuning", bert)


class StructureTests(unittest.TestCase):
    def test_long_survey_headings_ignore_lists_footnotes_and_reference_numbers(self):
        paper = _parsed("pdf3_30pages.pdf")
        labels = [s["label"] for s in section_length_stats(paper.structure, paper.raw_text)]
        self.assertEqual(labels, [
            "Opening context", "Introduction", "Definitions", "Related research fields",
            "Survey of the evaluations", "Survey of the recommendation classes",
            "Survey of the research field and shortcomings", "Summary and outlook", "References",
        ])
        self.assertIn("  4.7 Reproducibility and the butterfly effect", paper.structure["outline"])


class SectionFallbackTests(unittest.TestCase):
    def test_falls_back_to_parser_sections_without_junk_labels(self):
        structure = {"sections": {
            "preamble": "Title and authors " * 5,
            "Introduction": "word " * 40,
            "VGG-16": "row " * 40,
            "Method": "word " * 50,
        }}
        stats = section_length_stats(structure, raw_text="no headings here")
        self.assertEqual([s["label"] for s in stats], ["Introduction", "Method"])


if __name__ == "__main__":
    unittest.main()


class ClassificationProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_scoring_uses_gemini_even_when_menu_says_openrouter(self):
        from unittest import mock
        from app.services import analysis, providers

        seen = []

        async def fake_call(*_args, **_kwargs):
            seen.append(providers.chosen_provider.get())
            if len(seen) == 1:
                raise analysis.LLMRequestError("gemini busy")
            return '{"paper_type": "survey", "complexity": "high", "complexity_score": 7}'

        token = providers.chosen_provider.set("openrouter")
        try:
            with mock.patch.object(analysis, "call_openrouter", fake_call):
                result = await analysis.classify_paper("text " * 50)
        finally:
            providers.chosen_provider.reset(token)
        self.assertEqual(seen, ["gemini", "auto"])
        self.assertEqual(result["complexity_score"], 7)
