import unittest
from unittest import mock

import httpx

from app.services import references as R

from app.services.references import (
    _is_neurips_text,
    _neurips_record_blocks,
    _reference_metadata,
    _jmlr_record_blocks,
    extract_references,
    extract_reference_title,
    extract_arxiv_id,
    extract_isbn,
    normalize_title,
    verify_reference,
)


def _client(handler):
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        timeout=10,
    )


class ReferenceTests(unittest.IsolatedAsyncioTestCase):
    _NEURIPS_FIXTURE = """
    <html><body>
      <h1 class="book-title">Advances in Neural Information Processing Systems 30</h1>
      <a title="paper title" href="/paper_files/paper/2017/hash/unrelated-Abstract.html">
        Unrelated Proceedings Paper
      </a><span class="paper-authors">Other Author</span>
      <a title="paper title" href="/paper_files/paper/2017/hash/target-Abstract.html">
        Attention Is All You Need
      </a><span class="paper-authors">Ashish Vaswani, Noam Shazeer, Niki Parmar</span>
      <a title="paper title" href="/paper_files/paper/2017/hash/later-Abstract.html">
        Tensor Product Attention Is All You Need
      </a><span class="paper-authors">Different Author</span>
      <a title="paper title" href="/paper_files/paper/2017/hash/normal-Abstract.html">
        Another NeurIPS Paper
      </a><span class="paper-authors">Normal Author</span>
    </body></html>
    """

    async def test_neurips_archive_exact_match_is_verified(self):
        async def handler(request):
            self.assertEqual(str(request.url), "https://proceedings.neurips.cc/paper/2017")
            return httpx.Response(200, text=self._NEURIPS_FIXTURE, request=request)

        reference = (
            "Vaswani, A. et al. 2017. Attention Is All You Need. "
            "Advances in Neural Information Processing Systems 30."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["source"], "neurips")
        self.assertEqual(result["publication_relation"], "exact")
        self.assertEqual(result["matched_title"], "Attention Is All You Need")
        self.assertEqual(result["matched_year"], 2017)

    async def test_neurips_same_title_wrong_author_is_not_verified(self):
        async def handler(request):
            return httpx.Response(200, text=self._NEURIPS_FIXTURE, request=request)

        reference = (
            "Different, A. 2017. Attention Is All You Need. "
            "Advances in Neural Information Processing Systems 30."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertNotEqual(result["status"], "verified")
        self.assertIn("first_author", result.get("conflict_fields", []))

    async def test_neurips_venue_variants_are_scoped(self):
        for value in (
            "NeurIPS",
            "NIPS 2017",
            "Advances in Neural Information Processing Systems 30",
            "Adv. Neural Inf. Process. Syst.",
        ):
            self.assertTrue(_is_neurips_text(value))
        self.assertFalse(_is_neurips_text("neural information processing"))
        self.assertEqual(
            _reference_metadata(
                "Vaswani A 2017 Attention Is All You Need. "
                "Advances in Neural Information Processing Systems 30."
            ).venue,
            "neurips",
        )
        self.assertEqual(
            _reference_metadata(
                "Vaswani A 2017 Attention Is All You Need. "
                "Advances in Neural Information Processing Systems 30."
            ).volume,
            30,
        )
        self.assertIsNone(
            _reference_metadata(
                "Vaswani A 2017 Attention Is All You Need. NeurIPS 2017."
            ).volume
        )

    def test_neurips_archive_parser_ignores_navigation_and_extracts_records(self):
        records = _neurips_record_blocks(self._NEURIPS_FIXTURE, 2017)
        self.assertEqual(len(records), 4)
        target = next(
            record for record in records
            if record["title"] == ["Attention Is All You Need"]
        )
        self.assertEqual(target["author"][0]["family"], "vaswani")
        self.assertEqual(target["_source"], "neurips")
        self.assertEqual(target["volume"], "30")
        self.assertTrue(target["URL"].endswith("target-Abstract.html"))

    def test_extract_isbn_formats(self):
        self.assertEqual(extract_isbn("ISBN 978-0-262-03561-3"), "9780262035613")
        self.assertEqual(extract_isbn("ISBN 0-201-53082-1"), "0201530821")
        self.assertIsNone(extract_isbn("Sensors 12(9): 11734-11753"))
        self.assertEqual(extract_isbn("no identifier"), None)

    def test_author_year_references_are_split_before_appendix(self):
        text = (
            "Alan Akbik, Duncan Blythe, and Roland Vollgraf. 2018. "
            "Contextual string embeddings for sequence labeling. In COLING.\n"
            "Rami Al-Rfou, Dokook Choe, Noah Constant, Mandy Guo, and Llion Jones. "
            "2018. Character-level language modeling with deeper self-attention. "
            "arXiv preprint.\n"
            "Matthew Peters, Mark Neumann, and Luke Zettlemoyer. 2018a. "
            "Deep contextualized word representations. In NAACL.\n"
            "Appendix for the paper\n"
            "Additional implementation details that are not references."
        )
        references = extract_references({"sections": {"References": text}}, text)
        self.assertEqual(len(references), 3)
        self.assertTrue(references[0].startswith("Alan Akbik"))
        self.assertIn("Character-level language modeling", references[1])
        self.assertTrue(references[-1].startswith("Matthew Peters"))
        self.assertNotIn("Appendix", references[-1])

    def test_numbered_reference_continues_across_page_boundary(self):
        text = (
            "[1] Author, A. A complete reference whose title continues\n"
            "on the next page and includes venue information.\n"
            "[2] Author, B. Another complete reference with venue information."
        )
        references = extract_references({"sections": {"References": text}}, text)
        self.assertEqual(len(references), 2)
        self.assertIn("continues on the next page", references[0])
        self.assertNotIn("continues", references[1])

    async def test_strong_non_identifier_match_overcomes_weak_type_signal(self):
        async def handler(request):
            return httpx.Response(
                200,
                json={
                    "message": {
                        "items": [{
                            "title": [
                                "Overview and Evaluation of Bluetooth Low Energy: "
                                "An Emerging Low-Power Wireless Technology"
                            ],
                            "DOI": "10.3390/s120911734",
                            "author": [
                                {"family": "Gomez", "given": "Carles"},
                                {"family": "Oller", "given": "Joaquim"},
                                {"family": "Paradells", "given": "Josep"},
                            ],
                            "issued": {"date-parts": [[2012]]},
                            "type": "journal-article",
                            "container-title": ["Sensors"],
                        }]
                    }
                },
                request=request,
            )

        reference = (
            "Gomez C, Oller J and Paradells J 2012 Overview and evaluation of "
            "Bluetooth Low Energy: An emerging low-power wireless technology. "
            "Sensors 12(9): 11734-11753."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["similarity"], 1.0)

    async def test_strong_non_identifier_match_rejects_wrong_year(self):
        async def handler(request):
            return httpx.Response(
                200,
                json={
                    "message": {
                        "items": [{
                            "title": ["Overview and Evaluation of Bluetooth Low Energy"],
                            "author": [{"family": "Gomez"}],
                            "issued": {"date-parts": [[2018]]},
                            "type": "journal-article",
                        }]
                    }
                },
                request=request,
            )

        reference = (
            "Gomez C 2012 Overview and evaluation of Bluetooth Low Energy."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertNotEqual(result["status"], "verified")

    async def test_unseen_reference_with_matching_author_and_year_is_verified(self):
        async def handler(request):
            return httpx.Response(
                200,
                json={
                    "message": {
                        "items": [{
                            "title": ["A Bayesian View of Neural Compression"],
                            "author": [{"family": "Okafor", "given": "Nia"}],
                            "issued": {"date-parts": [[2023]]},
                            "container-title": ["Journal of Unfamiliar Methods"],
                            "type": "journal-article",
                        }]
                    }
                },
                request=request,
            )

        reference = (
            "Okafor N. 2023. A Bayesian View of Neural Compression. "
            "Journal of Unfamiliar Methods 7(2): 11-29."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["publication_relation"], "exact")

    async def test_missing_provider_authors_stays_uncertain(self):
        async def handler(request):
            return httpx.Response(
                200,
                json={
                    "message": {
                        "items": [{
                            "title": ["A Bayesian View of Neural Compression"],
                            "issued": {"date-parts": [[2023]]},
                            "container-title": ["Journal of Unfamiliar Methods"],
                            "type": "journal-article",
                        }]
                    }
                },
                request=request,
            )

        reference = (
            "Okafor N. 2023. A Bayesian View of Neural Compression. "
            "Journal of Unfamiliar Methods."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "uncertain")

    async def test_crossref_unavailable_can_fall_back_to_openalex(self):
        async def handler(request):
            if "api.crossref.org" in str(request.url):
                return httpx.Response(503, request=request)
            return httpx.Response(
                200,
                json={
                    "results": [{
                        "title": "A Bayesian View of Neural Compression",
                        "publication_year": 2023,
                        "authorships": [{
                            "author": {"display_name": "Nia Okafor"}
                        }],
                        "primary_location": {
                            "source": {
                                "display_name": "Journal of Unfamiliar Methods"
                            }
                        },
                    }]
                },
                request=request,
            )

        reference = (
            "Okafor N. 2023. A Bayesian View of Neural Compression. "
            "Journal of Unfamiliar Methods."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["source"], "openalex")

    async def test_jmlr_volume_lookup_verifies_exact_publication(self):
        async def handler(request):
            if "www.jmlr.org" in str(request.url):
                return httpx.Response(
                    200,
                    text=(
                        '<ul><li><a href="/papers/v7/lovelace20a.html">'
                        "A General Method for Reliable Inference</a> "
                        "by Ada Lovelace, Grace Hopper. 2020. JMLR 7: 101-120</li></ul>"
                    ),
                    request=request,
                )
            raise AssertionError("JMLR should verify before generic providers")

        reference = (
            "Lovelace A and Hopper G. 2020. A General Method for Reliable Inference. "
            "Journal of Machine Learning Research 7: 101-120."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["source"], "jmlr")
        self.assertEqual(result["publication_relation"], "exact")
        self.assertEqual(result["official_url"], "https://www.jmlr.org/papers/v7/lovelace20a.html")

    def test_jmlr_real_archive_shape_extracts_multiple_records(self):
        content = """
        <dl>
          <dt>Scikit-learn: Machine Learning in Python</dt>
          <dd><b><i>Fabian Pedregosa, Gaël Varoquaux</i></b>;
            (85):2825&minus;2830, 2011.
            [<a href="/papers/v12/pedregosa11a.html">abs</a>]
            [<a href="/papers/volume12/pedregosa11a/pedregosa11a.pdf">pdf</a>]
            [<a href="/papers/v12/pedregosa11a.bib">bib</a>]
          </dd>
          <dt>A General Method for Reliable Inference</dt>
          <dd><b><i>Ada Lovelace, Grace Hopper</i></b>;
            (42):1501-1536, 2011.
            [<a href="/papers/v12/lovelace11a.html">abs</a>]
            [<a href="/papers/v12/lovelace11a.bib">bib</a>]
          </dd>
          <dt>Robust Learning Under Shift</dt>
          <dd><b><i>Grace Hopper</i></b>;
            (43):1537–1560, 2011.
            [<a href="/papers/v12/hopper11a.html">abs</a>]
          </dd>
        </dl>
        """

        records = _jmlr_record_blocks(content)

        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]["title"], ["Scikit-learn: Machine Learning in Python"])
        self.assertEqual(records[0]["author"][0]["family"], "pedregosa")
        self.assertEqual(records[0]["volume"], "12")
        self.assertEqual(records[0]["issue"], "85")
        self.assertEqual(records[0]["page"], "2825-2830")
        self.assertEqual(records[0]["issued"]["date-parts"], [[2011]])
        self.assertEqual(
            records[0]["URL"],
            "https://www.jmlr.org/papers/v12/pedregosa11a.html",
        )
        self.assertEqual(records[1]["title"], ["A General Method for Reliable Inference"])
        self.assertEqual(records[2]["author"][0]["family"], "hopper")

    async def test_jmlr_real_archive_shape_verifies_scikit_learn(self):
        content = """
        <dl>
          <dt>Scikit-learn: Machine Learning in Python</dt>
          <dd><b><i>Fabian Pedregosa, Gaël Varoquaux, Alexandre Gramfort</i></b>;
            (85):2825−2830, 2011.
            [<a href="/papers/v12/pedregosa11a.html">abs</a>]
          </dd>
        </dl>
        """

        async def handler(request):
            if "www.jmlr.org" in str(request.url):
                return httpx.Response(200, text=content, request=request)
            raise AssertionError("JMLR should verify before generic providers")

        reference = (
            "Pedregosa F et al. 2011. Scikit-learn: Machine Learning in Python. "
            "Journal of Machine Learning Research 12: 2825-2830."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["source"], "jmlr")
        self.assertEqual(result["publication_relation"], "exact")
        self.assertEqual(result["matched_title"], "Scikit-learn: Machine Learning in Python")

    async def test_jmlr_abbreviation_does_not_require_full_venue(self):
        async def handler(request):
            return httpx.Response(
                200,
                text=(
                    '<li><a href="/papers/v8/chen21a.html">Robust Learning Under Shift</a> '
                    "by Wei Chen. 2021. JMLR 8: 44-61</li>"
                ),
                request=request,
            )

        reference = "Chen W. 2021. Robust Learning Under Shift. JMLR 8: 44-61."
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["source"], "jmlr")

    async def test_jmlr_wrong_pages_are_not_exact(self):
        async def handler(request):
            if "www.jmlr.org" in str(request.url):
                return httpx.Response(
                    200,
                    text=(
                        '<li><a href="/papers/v9/paper22a.html">A New JMLR Paper</a> '
                        "by Sam Lee. 2022. JMLR 9: 100-120</li>"
                    ),
                    request=request,
                )
            if "api.crossref.org" in str(request.url):
                return httpx.Response(200, json={"message": {"items": []}}, request=request)
            return httpx.Response(200, json={"results": []}, request=request)

        reference = "Lee S. 2022. A New JMLR Paper. JMLR 9: 101-121."
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertNotEqual(result["status"], "verified")

    async def test_jmlr_explicit_page_conflict_cannot_be_overridden_by_openalex(self):
        async def handler(request):
            if "www.jmlr.org" in str(request.url):
                return httpx.Response(
                    200,
                    text=(
                        "<dl><dt>Fast SVM Training Using Approximate Extreme Points</dt>"
                        "<dd><b><i>Nandan, Khargonekar, Talathi</i></b>; "
                        "(2):59-98, 2014. "
                        '<a href="/papers/v15/nandan14a.html">abs</a></dd></dl>'
                    ),
                    request=request,
                )
            if "api.crossref.org" in str(request.url):
                return httpx.Response(200, json={"message": {"items": []}}, request=request)
            if "api.openalex.org" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "results": [{
                            "title": "Fast SVM Training Using Approximate Extreme Points",
                            "publication_year": 2014,
                            "authorships": [
                                {"author": {"display_name": "Nandan S"}},
                                {"author": {"display_name": "Khargonekar P"}},
                            ],
                            "primary_location": {
                                "source": {
                                    "display_name": "Journal of Machine Learning Research"
                                }
                            },
                        }]
                    },
                    request=request,
                )
            raise AssertionError(f"Unexpected provider URL: {request.url}")

        reference = (
            "Nandan S and Khargonekar P and Talathi R. 2014. "
            "Fast SVM Training Using Approximate Extreme Points. "
            "Journal of Machine Learning Research 15: 60-99."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["source"], "jmlr")
        self.assertEqual(result["publication_relation"], "possible_related")
        self.assertEqual(result["conflict_fields"], ["pages"])

    async def test_jmlr_conflict_fields_capture_explicit_metadata_mismatches(self):
        async def handler(request):
            if "www.jmlr.org" in str(request.url):
                return httpx.Response(
                    200,
                    text=(
                        "<dl><dt>Fast SVM Training Using Approximate Extreme Points</dt>"
                        "<dd><b><i>Nandan, Khargonekar, Talathi</i></b>; "
                        "(2):59-98, 2014. "
                        '<a href="/papers/v15/nandan14a.html">abs</a></dd></dl>'
                    ),
                    request=request,
                )
            if "api.crossref.org" in str(request.url):
                return httpx.Response(200, json={"message": {"items": []}}, request=request)
            return httpx.Response(200, json={"results": []}, request=request)

        references = {
            "first_author": (
                "Smith S and Khargonekar P and Talathi R. 2014. "
                "Fast SVM Training Using Approximate Extreme Points. JMLR 15(2): 59-98."
            ),
            "year": (
                "Nandan S and Khargonekar P and Talathi R. 2019. "
                "Fast SVM Training Using Approximate Extreme Points. JMLR 15(2): 59-98."
            ),
            "volume": (
                "Nandan S and Khargonekar P and Talathi R. 2014. "
                "Fast SVM Training Using Approximate Extreme Points. JMLR 16(2): 59-98."
            ),
            "issue": (
                "Nandan S and Khargonekar P and Talathi R. 2014. "
                "Fast SVM Training Using Approximate Extreme Points. JMLR 15(7): 59-98."
            ),
        }
        for field, reference in references.items():
            async with _client(handler) as client:
                result = await verify_reference(client, reference, "")
            self.assertNotEqual(result["status"], "verified", field)
            self.assertIn(field, result["conflict_fields"], field)

    async def test_jmlr_failure_falls_back_to_crossref(self):
        async def handler(request):
            if "www.jmlr.org" in str(request.url):
                return httpx.Response(503, request=request)
            if "api.crossref.org" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "message": {
                            "items": [{
                                "title": ["A General Method for Reliable Inference"],
                                "author": [{"family": "Lovelace"}],
                                "issued": {"date-parts": [[2020]]},
                                "container-title": ["Journal of Machine Learning Research"],
                                "volume": "7",
                                "page": "101-120",
                            }]
                        }
                    },
                    request=request,
                )
            return httpx.Response(200, json={"results": []}, request=request)

        reference = (
            "Lovelace A. 2020. A General Method for Reliable Inference. "
            "Journal of Machine Learning Research 7: 101-120."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["source"], "crossref")

    async def test_machine_learning_venue_does_not_trigger_jmlr(self):
        calls = []

        async def handler(request):
            calls.append(str(request.url))
            if "api.crossref.org" in str(request.url):
                return httpx.Response(200, json={"message": {"items": []}}, request=request)
            return httpx.Response(200, json={"results": []}, request=request)

        reference = "Smith S. 2020. A Study in Machine Learning. Machine Learning 10: 1-10."
        async with _client(handler) as client:
            await verify_reference(client, reference, "")
        self.assertTrue(all("www.jmlr.org" not in call for call in calls))

    async def test_book_is_verified_with_publisher_and_isbn(self):
        async def handler(request):
            return httpx.Response(
                200,
                json={
                    "message": {
                        "items": [{
                            "title": ["Deep Learning"],
                            "author": [
                                {"family": "Goodfellow"},
                                {"family": "Bengio"},
                                {"family": "Courville"},
                            ],
                            "issued": {"date-parts": [[2016]]},
                            "publisher": "MIT Press",
                            "type": "book",
                            "ISBN": ["9780262035613"],
                        }]
                    }
                },
                request=request,
            )

        reference = (
            "Goodfellow I, Bengio Y, Courville A. 2016. Deep Learning. "
            "MIT Press. ISBN 978-0-262-03561-3."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "verified")
        self.assertTrue(result["isbn_match"])

    async def test_book_does_not_verify_against_article(self):
        async def handler(request):
            return httpx.Response(
                200,
                json={
                    "message": {
                        "items": [{
                            "title": ["Deep Learning"],
                            "author": [{"family": "Goodfellow"}],
                            "issued": {"date-parts": [[2016]]},
                            "container-title": ["Nature"],
                            "type": "journal-article",
                        }]
                    }
                },
                request=request,
            )

        reference = "Goodfellow I. 2016. Deep Learning. MIT Press. ISBN 9780262035613."
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "not_found")

    def test_extract_arxiv_ids(self):
        self.assertEqual(extract_arxiv_id("arXiv:1301.3781"), "1301.3781")
        self.assertEqual(extract_arxiv_id("https://arxiv.org/abs/1301.3781"), "1301.3781")
        self.assertEqual(extract_arxiv_id("https://www.arxiv.org/pdf/1301.3781v2."), "1301.3781")

    async def test_arxiv_record_is_verified_without_crossref_search(self):
        async def handler(request):
            self.assertIn("export.arxiv.org", str(request.url))
            return httpx.Response(
                200,
                text="""<?xml version="1.0"?>
                <feed xmlns="http://www.w3.org/2005/Atom"
                      xmlns:arxiv="http://arxiv.org/schemas/atom">
                  <entry>
                    <title>Efficient Estimation of Word Representations in Vector Space</title>
                    <published>2013-01-01T00:00:00Z</published>
                    <author><name>Tomas Mikolov</name></author>
                    <author><name>Kai Chen</name></author>
                    <author><name>Greg Corrado</name></author>
                    <author><name>Jeffrey Dean</name></author>
                  </entry>
                </feed>""",
                request=request,
            )

        reference = (
            "[7] Mikolov, T., Chen, K., Corrado, G. and Dean, J. 2013. "
            "Efficient Estimation of Word Representations in Vector Space. "
            "arXiv:1301.3781."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["source"], "arxiv")
        self.assertEqual(result["matched_year"], 2013)

    async def test_arxiv_wrong_title_is_not_verified(self):
        async def handler(request):
            return httpx.Response(
                200,
                text="""<feed xmlns="http://www.w3.org/2005/Atom">
                  <entry>
                    <title>Efficient Estimation of Nepali Word Representations in Vector Space</title>
                    <published>2013-01-01T00:00:00Z</published>
                    <author><name>Tomas Mikolov</name></author>
                  </entry>
                </feed>""",
                request=request,
            )

        reference = (
            "Mikolov T. 2013. Efficient Estimation of Word Representations in Vector Space. "
            "arXiv:1301.3781."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertNotEqual(result["status"], "verified")

    async def test_openalex_verifies_when_crossref_candidate_is_wrong(self):
        async def handler(request):
            if "api.crossref.org" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "message": {
                            "items": [{
                                "title": ["Getting Started with Scikit-learn for Machine Learning"],
                                "issued": {"date-parts": [[2019]]},
                                "DOI": "10.1000/wrong",
                            }]
                        }
                    },
                    request=request,
                )
            return httpx.Response(
                200,
                json={
                    "results": [{
                        "title": "Scikit-learn: Machine Learning in Python",
                        "publication_year": 2011,
                        "authorships": [{"author": {"display_name": "Fabian Pedregosa"}}],
                        "primary_location": {
                            "source": {"display_name": "Journal of Machine Learning Research"}
                        },
                    }]
                },
                request=request,
            )

        reference = (
            "Pedregosa F et al. 2011. Scikit-learn: Machine Learning in Python. "
            "Journal of Machine Learning Research 12: 2825-2830."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["source"], "openalex")

    async def test_doi_reference_falls_back_to_openalex_when_crossref_is_down(self):
        async def handler(request):
            if "api.crossref.org" in str(request.url):
                return httpx.Response(503, request=request)
            return httpx.Response(
                200,
                json={"results": [{
                    "title": "A Bayesian View of Neural Compression",
                    "publication_year": 2023,
                    "doi": "https://doi.org/10.1000/xyz",
                    "authorships": [{"author": {"display_name": "Nia Okafor"}}],
                    "primary_location": {"source": {"display_name": "Journal of Unfamiliar Methods"}},
                }]},
                request=request,
            )

        reference = (
            "Okafor N. 2023. A Bayesian View of Neural Compression. "
            "Journal of Unfamiliar Methods. DOI: 10.1000/xyz."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["source"], "openalex")
        self.assertNotEqual(result["status"], "unavailable")

    async def test_openalex_api_key_is_sent_when_configured(self):
        seen = []

        async def handler(request):
            if "api.openalex.org" in str(request.url):
                seen.append(request.url.params.get("api_key"))
                return httpx.Response(200, json={"results": []}, request=request)
            return httpx.Response(200, json={"message": {"items": []}}, request=request)

        reference = "Okafor N. 2023. A Bayesian View of Neural Compression. Journal of Unfamiliar Methods."
        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient
        with mock.patch.object(R.httpx, "AsyncClient", lambda **kw: real_client(transport=transport, **kw)):
            await R.verify_all([reference], "", openalex_api_key="k123")
        self.assertEqual(seen, ["k123"])

    async def test_openalex_not_called_for_doi_or_arxiv(self):
        calls = []

        async def handler(request):
            calls.append(str(request.url))
            if "api.crossref.org" in str(request.url):
                return httpx.Response(404, request=request)
            raise AssertionError("unexpected secondary provider call")

        async with _client(handler) as client:
            doi_result = await verify_reference(
                client, "[1] Smith J 2020 A title. DOI: 10.1000/missing.", ""
            )
        self.assertEqual(doi_result["status"], "not_found")
        self.assertTrue(all("openalex.org" not in call for call in calls))
    async def test_neurips_first_name_first_author_list_is_verified(self):
        # BERT (NAACL 2019) bibliography style: "First Last" author names.
        async def handler(request):
            return httpx.Response(200, text=self._NEURIPS_FIXTURE, request=request)

        reference = (
            "Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, "
            "Aidan N Gomez, Lukasz Kaiser, and Illia Polosukhin. 2017. Attention is all "
            "you need. In Advances in Neural Information Processing Systems, pages 6000–6010."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "verified")
        self.assertNotIn("first_author", result.get("conflict_fields") or [])

    def test_author_surnames_across_bibliography_styles(self):
        cases = {
            # Real entries from test-pdfs/ (BERT NAACL 2019, ResNet CVPR 2016).
            "Rie Kubota Ando and Tong Zhang. 2005. A framework for learning predictive "
            "structures from multiple tasks and unlabeled data. Journal of Machine "
            "Learning Research, 6(Nov):1817–1853.": ["ando", "zhang"],
            "Kevin Clark, Minh-Thang Luong, Christopher D Manning, and Quoc Le. 2018. "
            "Semi-supervised sequence modeling with cross-view training.": ["clark", "luong"],
            "J. Deng, W. Dong, R. Socher, L.-J. Li, K. Li, and L. FeiFei. 2009. ImageNet: "
            "A Large-Scale Hierarchical Image Database. In CVPR09 .": ["deng", "dong"],
            "[9] I. J. Goodfellow, D. Warde-Farley, M. Mirza, A. Courville, and Y. Bengio. "
            "Maxout networks. arXiv:1302.4389 , 2013.": ["goodfellow"],
            "Vaswani, A. et al. 2017. Attention Is All You Need.": ["vaswani"],
        }
        for reference, expected in cases.items():
            surnames = _reference_metadata(reference).author_surnames
            self.assertEqual(surnames[: len(expected)], expected, reference)

    def test_trailing_year_style_titles(self):
        # CVPR/IEEE style puts the year last; the title follows the author block.
        self.assertEqual(
            extract_reference_title(
                "[9] I. J. Goodfellow, D. Warde-Farley, M. Mirza, A. Courville, and "
                "Y. Bengio. Maxout networks. arXiv:1302.4389 , 2013."
            ),
            "Maxout networks",
        )
        self.assertEqual(
            extract_reference_title(
                "[6] R. Girshick. Fast R-CNN. In ICCV, 2015."
            ),
            "Fast R-CNN",
        )

    def test_year_with_disambiguation_suffix(self):
        metadata = _reference_metadata(
            "Matthew Peters, Mark Neumann, Mohit Iyyer, Matt Gardner, Christopher Clark, "
            "Kenton Lee, and Luke Zettlemoyer. 2018a. Deep contextualized word "
            "representations. In NAACL."
        )
        self.assertEqual(metadata.year, 2018)
        self.assertEqual(metadata.first_author, "peters")
        self.assertEqual(metadata.title, "Deep contextualized word representations")

    def test_extract_reference_titles_and_normalization(self):
        reference = "[4] Breiman L 2001 Random forests. Machine Learning 45: 5-32."
        self.assertEqual(extract_reference_title(reference), "Random forests")
        self.assertEqual(
            normalize_title("Attention Is All You Need"),
            normalize_title("attention-is all you need"),
        )

    async def test_matching_title_is_verified_even_with_authors_and_journal(self):
        async def handler(request):
            return httpx.Response(
                200,
                json={
                    "message": {
                        "items": [
                            {
                                "title": ["Random Forests"],
                                "DOI": "10.1023/a:1010933404324",
                                "author": [{"family": "Breiman"}],
                                "issued": {"date-parts": [[2001]]},
                            }
                        ]
                    }
                },
                request=request,
            )

        async with _client(handler) as client:
            result = await verify_reference(
                client,
                "[4] Breiman L 2001 Random forests. Machine Learning 45: 5-32.",
                "",
            )
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["similarity"], 1.0)

    async def test_scikit_learn_title_is_verified(self):
        async def handler(request):
            return httpx.Response(
                200,
                json={
                    "message": {
                        "items": [
                            {
                                "title": ["Scikit-learn: Machine Learning in Python"],
                                "author": [{"family": "Pedregosa"}],
                                "issued": {"date-parts": [[2011]]},
                            }
                        ]
                    }
                },
                request=request,
            )

        reference = (
            "[5] Pedregosa F et al. 2011 Scikit-learn: Machine learning in Python. "
            "Journal of Machine Learning Research 12: 2825-2830."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "verified")

    async def test_scikit_learn_arxiv_record_is_same_work_version(self):
        async def handler(request):
            return httpx.Response(
                200,
                json={
                    "message": {
                        "items": [{
                            "title": ["Scikit-learn: Machine Learning in Python"],
                            "DOI": "10.48550/arxiv.1201.0490",
                            "author": [{"family": "Pedregosa", "given": "Fabian"}],
                            "issued": {"date-parts": [[2012]]},
                            "type": "journal-article",
                        }]
                    }
                },
                request=request,
            )

        reference = (
            "Pedregosa F et al. 2011. Scikit-learn: Machine Learning in Python. "
            "Journal of Machine Learning Research 12: 2825-2830."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["publication_relation"], "same_work_version")
        self.assertEqual(
            result["match_reason"],
            "same scholarly work found as a different preprint/publication version",
        )

    async def test_same_title_different_authors_is_different_work(self):
        async def handler(request):
            return httpx.Response(
                200,
                json={
                    "message": {
                        "items": [{
                            "title": ["Attention Is All You Need"],
                            "author": [{"family": "Different"}],
                            "issued": {"date-parts": [[2025]]},
                            "DOI": "10.65215/r5bs2d54",
                        }]
                    }
                },
                request=request,
            )

        reference = (
            "Vaswani A et al. 2017. Attention Is All You Need. "
            "Advances in Neural Information Processing Systems 30."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["publication_relation"], "different_work")
        self.assertEqual(
            result["match_reason"],
            "same title but conflicting author/year metadata",
        )

    async def test_same_authors_different_year_is_possible_related_work(self):
        async def handler(request):
            return httpx.Response(
                200,
                json={
                    "message": {
                        "items": [{
                            "title": ["Attention Is All You Need"],
                            "author": [{"family": "Vaswani", "given": "Ashish"}],
                            "issued": {"date-parts": [[2018]]},
                            "type": "journal-article",
                        }]
                    }
                },
                request=request,
            )

        reference = "Vaswani A 2017 Attention Is All You Need."
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(result["publication_relation"], "possible_related")

    async def test_attention_title_is_verified(self):
        async def handler(request):
            return httpx.Response(
                200,
                json={
                    "message": {
                        "items": [
                            {
                                "title": ["Attention Is All You Need"],
                                "author": [{"family": "Vaswani"}],
                                "issued": {"date-parts": [[2017]]},
                            }
                        ]
                    }
                },
                request=request,
            )

        reference = (
            "[6] Vaswani A et al. 2017 Attention is all you need. "
            "Advances in Neural Information Processing Systems 30."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "verified")

    async def test_best_title_is_selected_from_all_candidates(self):
        async def handler(request):
            return httpx.Response(
                200,
                json={
                    "message": {
                        "items": [
                            {"title": ["Unrelated result"], "issued": {"date-parts": [[2001]]}},
                            {
                                "title": ["Random Forests"],
                                "author": [{"family": "Breiman"}],
                                "issued": {"date-parts": [[2001]]},
                            },
                        ]
                    }
                },
                request=request,
            )

        async with _client(handler) as client:
            result = await verify_reference(
                client,
                "[4] Breiman L 2001 Random forests. Machine Learning 45: 5-32.",
                "",
            )
        self.assertEqual(result["matched_title"], "Random Forests")
        self.assertEqual(result["status"], "verified")

    async def test_wrong_year_is_uncertain(self):
        async def handler(request):
            return httpx.Response(
                200,
                json={
                    "message": {
                        "items": [
                            {"title": ["Random Forests"], "issued": {"date-parts": [[2002]]}}
                        ]
                    }
                },
                request=request,
            )

        async with _client(handler) as client:
            result = await verify_reference(
                client,
                "[4] Breiman L 2001 Random forests. Machine Learning 45: 5-32.",
                "",
            )
        self.assertEqual(result["status"], "uncertain")

    async def test_rate_limit_becomes_unavailable_after_retries(self):
        calls = 0

        async def handler(request):
            nonlocal calls
            calls += 1
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)

        async with _client(handler) as client:
            result = await verify_reference(
                client,
                "[7] Devlin J et al. 2019 BERT: Pre-training of deep bidirectional "
                "transformers for language understanding. Proceedings of NAACL-HLT.",
                "",
            )
        self.assertEqual(calls, 6)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("429", result["error"])

    async def test_missing_doi_is_not_found(self):
        async def handler(request):
            return httpx.Response(404, request=request)

        async with _client(handler) as client:
            result = await verify_reference(
                client,
                "[8] Smith J 2024 A fabricated title. DOI: 10.9999/ijss.2024.184201.",
                "",
            )
        self.assertEqual(result["status"], "not_found")
        self.assertIsNone(result["error"])

    async def test_exact_doi_metadata_is_verified(self):
        async def handler(request):
            return httpx.Response(
                200,
                json={
                    "message": {
                        "title": [
                            "Text categorization with Support Vector Machines: "
                            "Learning with many relevant features"
                        ],
                        "DOI": "10.1007/bfb0026683",
                        "author": [{"family": "Joachims", "given": "Thorsten"}],
                        "issued": {"date-parts": [[1998]]},
                        "type": "proceedings-article",
                        "container-title": ["Machine Learning: ECML-98"],
                    }
                },
                request=request,
            )

        reference = (
            "[8] Joachims, T. 1998. Text Categorization with Support Vector Machines: "
            "Learning with Many Relevant Features. Machine Learning: ECML-98, 137-142. "
            "DOI: 10.1007/BFb0026683."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["doi_score"], 1.0)
        self.assertEqual(result["title_score"], 1.0)
        self.assertEqual(result["author_score"], 1.0)
        self.assertEqual(result["year_score"], 1.0)

    async def test_exact_doi_with_different_first_author_is_not_verified(self):
        async def handler(request):
            return httpx.Response(
                200,
                json={
                    "message": {
                        "title": ["Random Forests"],
                        "DOI": "10.1023/A:1010933404324",
                        "author": [{"family": "Different", "given": "Author"}],
                        "issued": {"date-parts": [[2001]]},
                        "type": "journal-article",
                    }
                },
                request=request,
            )

        reference = (
            "[3] Breiman, L. 2001. Random forests. Machine Learning 45(1): "
            "5-32. DOI: 10.1023/A:1010933404324."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertNotEqual(result["status"], "verified")
        self.assertEqual(result["author_score"], 0.0)
        self.assertFalse(result["author_matches"])

    async def test_doi_author_matching_accepts_initials_and_accents(self):
        async def handler(request):
            return httpx.Response(
                200,
                json={
                    "message": {
                        "title": [
                            "Overview and evaluation of Bluetooth Low Energy: "
                            "An emerging low-power wireless technology"
                        ],
                        "DOI": "10.3390/s120911734",
                        "author": [
                            {"family": "Gómez", "given": "Carles"},
                            {"family": "Oller", "given": "Joaquim"},
                            {"family": "Paradells", "given": "Josep"},
                        ],
                        "issued": {"date-parts": [[2012]]},
                        "type": "journal-article",
                    }
                },
                request=request,
            )

        reference = (
            "[3] Gomez C, Oller J and Paradells J 2012 Overview and evaluation "
            "of Bluetooth Low Energy: An emerging low-power wireless technology. "
            "Sensors 12(9): 11734-11753. DOI: 10.3390/s120911734."
        )
        async with _client(handler) as client:
            result = await verify_reference(client, reference, "")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["author_score"], 1.0)
        self.assertTrue(result["author_matches"])

    async def test_exact_doi_matches_are_not_downgraded_by_generic_scoring(self):
        records = {
            "10.1023/a:1010933404324": {
                "title": ["Random Forests"],
                "DOI": "10.1023/A:1010933404324",
                "author": [{"family": "Breiman", "given": "Leo"}],
                "issued": {"date-parts": [[2001]]},
                "type": "journal-article",
                "container-title": ["Machine Learning"],
            },
            "10.1007/bfb0026683": {
                "title": [
                    "Text Categorization with Support Vector Machines: "
                    "Learning with Many Relevant Features"
                ],
                "DOI": "10.1007/BFb0026683",
                "author": [{"family": "Joachims", "given": "Thorsten"}],
                "issued": {"date-parts": [[1998]]},
                "type": "proceedings-article",
                "container-title": ["Machine Learning: ECML-98"],
            },
            "10.3390/s120911734": {
                "title": [
                    "Overview and evaluation of Bluetooth Low Energy: "
                    "An emerging low-power wireless technology"
                ],
                "DOI": "10.3390/s120911734",
                "author": [
                    {"family": "Gomez", "given": "Carles"},
                    {"family": "Oller", "given": "Jordi"},
                    {"family": "Paradells", "given": "Josep"},
                ],
                "issued": {"date-parts": [[2012]]},
                "type": "journal-article",
                "container-title": ["Sensors"],
            },
        }

        async def handler(request):
            doi = str(request.url).split("/works/", 1)[-1].lower()
            return httpx.Response(
                200,
                json={"message": records[doi]},
                request=request,
            )

        references = [
            (
                "[3] Breiman, L. 2001. Random forests. Machine Learning 45(1): "
                "5-32. DOI: 10.1023/A:1010933404324."
            ),
            (
                "[8] Joachims, T. 1998. Text Categorization with Support Vector "
                "Machines: Learning with Many Relevant Features. Machine Learning: "
                "ECML-98, 137-142. DOI: 10.1007/BFb0026683."
            ),
            (
                "[3] Gomez C, Oller J and Paradells J 2012 Overview and evaluation "
                "of Bluetooth Low Energy: An emerging low-power wireless technology. "
                "Sensors 12(9): 11734-11753. DOI: 10.3390/s120911734."
            ),
        ]

        async with _client(handler) as client:
            results = [
                await verify_reference(client, reference, "")
                for reference in references
            ]

        self.assertEqual([result["status"] for result in results], [
            "verified",
            "verified",
            "verified",
        ])
        self.assertEqual([result["similarity"] for result in results], [1.0, 1.0, 1.0])
        self.assertEqual(
            [result["matched_doi"] for result in results],
            list(records),
        )

if __name__ == "__main__":
    unittest.main()
