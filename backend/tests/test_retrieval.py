import unittest

from app.services.chunking import chunk_paper
from app.services.retrieval import retrieve_relevant_chunks, tokenize

PAPER = """Abstract
We survey recommender systems and find that content-based filtering dominates.
1 Introduction
Recommenders help people find papers.
2 Methods
2.1 Filtering
Collaborative filters use ratings from many users.
3 Conclusion
Our main finding is that evaluations are rarely reproducible.
"""


class RetrievalTests(unittest.TestCase):
    def test_stems_and_drops_question_words(self):
        self.assertEqual(tokenize("What filters were used?"), ["filter"])

    def test_passages_carry_subsection_labels(self):
        sections = {c["section"] for c in chunk_paper(PAPER, None)}
        self.assertIn("2 Methods › 2.1 Filtering", sections)

    def test_abstract_always_included_and_broad_questions_reach_conclusion(self):
        picked = retrieve_relevant_chunks("What are the main results?", chunk_paper(PAPER, None), top_k=3)
        self.assertEqual(picked[0]["section"], "Abstract")
        self.assertIn("3 Conclusion", [c["section"] for c in picked])

    def test_follow_up_uses_previous_question(self):
        picked = retrieve_relevant_chunks("and how do they work?", chunk_paper(PAPER, None), top_k=2,
                                          context="What are collaborative filters?")
        self.assertIn("Collaborative", picked[1]["text"])


if __name__ == "__main__":
    unittest.main()
