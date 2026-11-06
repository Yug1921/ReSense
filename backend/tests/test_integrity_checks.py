import asyncio
import os
import unittest
from unittest import mock

for _name in ("SUPABASE_URL", "SUPABASE_KEY", "OPENROUTER_API_KEY"):
    os.environ.setdefault(_name, "test")

import httpx
from fastapi.testclient import TestClient

from app.auth import CurrentUser, current_user
from app.main import app
from app.routers import integrity
from app.services import claims, links, retractions
from tests.test_integrity_router import _FakeSupabase, _paper


class RetractionTests(unittest.TestCase):
    # Shape of Crossref's answer for the retracted 1998 Lancet paper.
    ITEMS = [
        {"DOI": "10.1016/s0140-6736(10)60175-4", "update-to": [{
            "DOI": "10.1016/s0140-6736(97)11096-0", "type": "retraction", "label": "Retraction",
            "source": "retraction-watch", "updated": {"date-parts": [[2010, 2, 6]]}}]},
        {"DOI": "10.1016/s0140-6736(04)15715-2", "update-to": [{
            "DOI": "10.1016/s0140-6736(97)11096-0", "type": "correction", "label": "Correction",
            "updated": {"date-parts": [[2004, 3, 6]]}}]},
        {"DOI": "10.1/other", "update-to": [{"DOI": "10.9/not-asked", "type": "retraction"}]},
    ]

    def test_notices_are_matched_to_the_cited_doi_most_serious_first(self):
        found = retractions._parse(self.ITEMS, {"10.1016/s0140-6736(97)11096-0"})
        notices = found["10.1016/s0140-6736(97)11096-0"]
        self.assertEqual([n["type"] for n in notices], ["retraction", "correction"])
        self.assertEqual(notices[0]["date"], "2010-02-06")
        self.assertEqual(notices[0]["source"], "Retraction Watch")
        self.assertNotIn("10.9/not-asked", found)
        self.assertTrue(retractions.is_serious(notices))
        self.assertFalse(retractions.is_serious(notices[1:]))

    def test_duplicate_notice_from_two_sources_is_kept_once(self):
        twice = self.ITEMS[:1] + [{**self.ITEMS[0], "DOI": "10.1016/dup"}]
        found = retractions._parse(twice, {"10.1016/s0140-6736(97)11096-0"})
        self.assertEqual(len(found["10.1016/s0140-6736(97)11096-0"]), 1)


class LinkExtractionTests(unittest.TestCase):
    def test_wrapped_urls_are_joined_and_footnote_text_is_not(self):
        # Real line breaks from the BERT and ResNet PDFs.
        text = (
            "13https://cloudplatform.googleblog.com/2018/06/Cloud-\nTPU-now-offers-preemptible-pricing-and-global-\n"
            "availability.html\n1http://image-net.org/challenges/LSVRC/2015/\nand\nhttp://mscoco.org/dataset/#detections-challenge2015.\n"
            "2 http://citeseerx.ist.psu.edu.\n3 http://example.org/x\nsee https://gluebenchmark.com/leaderboard).The next\n"
        )
        urls = [link["url"] for link in links.extract_links(text)]
        self.assertEqual(urls, [
            "https://cloudplatform.googleblog.com/2018/06/Cloud-TPU-now-offers-preemptible-pricing-and-global-availability.html",
            "http://image-net.org/challenges/LSVRC/2015/",
            "http://mscoco.org/dataset/#detections-challenge2015",
            "http://citeseerx.ist.psu.edu",
            "http://example.org/x",
            "https://gluebenchmark.com/leaderboard",
        ])

    def test_links_after_the_reference_heading_are_marked_as_references(self):
        text = "Code at https://a.org/code.\nReferences\n[1] B. Site https://b.org/page"
        found = links.extract_links(text, references_start=text.index("References"))
        self.assertEqual([(l["url"], l["where"]) for l in found], [("https://a.org/code", "body"), ("https://b.org/page", "references")])

    def test_availability_statements(self):
        body = (
            "We trained a model. The data that support the findings of this study are available from the "
            "corresponding author upon reasonable request. The code and pre-trained models are available at "
            "https://github.com/google-research/bert. Other datasets are often not publicly available. "
            "Results are available within minutes."
        )
        found = links.availability_statements(body)
        self.assertEqual([s["kind"] for s in found], ["on_request", "public"])
        self.assertIn("upon reasonable request", found[0]["text"])


class LinkCheckingTests(unittest.TestCase):
    def _run(self, handler, urls, public=True, dns_ok=True):
        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient

        def client(**kwargs):
            return real_client(transport=transport, **kwargs)

        async def resolve(host):
            if host == "gone.example":
                raise httpx.ConnectError("Domain not found: [Errno -2] Name or service not known")
            if not public or host == "localhost":
                raise links._Blocked(host)

        with mock.patch.object(links.httpx, "AsyncClient", client), \
                mock.patch.object(links, "_resolve_public", resolve), \
                mock.patch.object(links, "_dns_works", return_value=dns_ok):
            items = [{"url": u, "where": "body", "context": ""} for u in urls]
            return {r["url"]: r for r in asyncio.run(links.check_links(items))}

    def test_statuses(self):
        def handler(request):
            path = request.url.path
            if path == "/ok":
                return httpx.Response(200)
            if path == "/gone":
                return httpx.Response(404)
            if path == "/moved":
                return httpx.Response(301, headers={"location": "https://site.example/ok"})
            if path == "/nohead":
                return httpx.Response(405) if request.method == "HEAD" else httpx.Response(200)
            if path == "/blocked":
                return httpx.Response(403)
            raise httpx.ReadTimeout("slow", request=request)

        found = self._run(handler, [
            "https://site.example/ok", "https://site.example/gone", "https://site.example/moved",
            "https://site.example/nohead", "https://site.example/blocked", "https://site.example/slow",
            "https://gone.example/x",
        ])
        status = {url.rsplit("/", 1)[-1]: r["status"] for url, r in found.items()}
        self.assertEqual(status, {"ok": "working", "gone": "broken", "moved": "working", "nohead": "working",
                                  "blocked": "unconfirmed", "slow": "unconfirmed", "x": "broken"})
        self.assertEqual(found["https://site.example/moved"]["final_url"], "https://site.example/ok")
        self.assertIn("domain", found["https://gone.example/x"]["note"])

    def test_missing_domain_is_not_called_dead_when_lookups_fail_everywhere(self):
        found = self._run(lambda r: httpx.Response(200), ["https://gone.example/x"], dns_ok=False)
        self.assertEqual(found["https://gone.example/x"]["status"], "unconfirmed")

    def test_private_addresses_are_never_fetched(self):
        def handler(request):
            raise AssertionError("a private address was requested")

        found = self._run(handler, ["http://localhost/admin"])
        self.assertEqual(found["http://localhost/admin"]["status"], "skipped")

    def test_redirect_to_a_private_address_is_stopped(self):
        def handler(request):
            if request.url.host == "site.example":
                return httpx.Response(302, headers={"location": "http://localhost/secret"})
            raise AssertionError("followed a redirect into a private address")

        found = self._run(handler, ["https://site.example/go"])
        self.assertEqual(found["https://site.example/go"]["status"], "skipped")

    def test_public_host_check(self):
        with mock.patch.object(links.socket, "getaddrinfo", return_value=[(0, 0, 0, "", ("127.0.0.1", 0))]):
            self.assertFalse(links._public_host("evil.example"))
        with mock.patch.object(links.socket, "getaddrinfo", return_value=[(0, 0, 0, "", ("140.82.112.3", 0))]):
            self.assertTrue(links._public_host("github.com"))


class CitationTests(unittest.TestCase):
    NUMBERED_REFS = [
        {"index": 1, "raw": "[1] Y. Bengio. Learning long-term dependencies. 1994."},
        {"index": 2, "raw": "[2] C. M. Bishop. Neural networks for pattern recognition. 1995."},
        {"index": 3, "raw": "[3] W. L. Briggs. A multigrid tutorial. 2000."},
        {"index": 4, "raw": "[4] K. Chatfield. The devil is in the details. 2011."},
    ]

    def test_numbered_citations_and_ranges(self):
        body = (
            "Deep networks were shown to suffer from vanishing gradients [1]. "
            "Several methods exist [2-4], e.g. multigrid [3]. Table 1 2 3 4 5 6 7 8 9 [1]."
        )
        found = claims.find_citations(body, self.NUMBERED_REFS)
        self.assertEqual([c["refs"] for c in found], [[1], [2, 3, 4]])

    def test_author_year_citations(self):
        refs = [
            {"index": 1, "raw": "Alec Radford, Karthik Narasimhan. 2018. Improving language understanding."},
            {"index": 2, "raw": "Matthew Peters, Mark Neumann. 2018a. Deep contextualized word representations."},
            {"index": 3, "raw": "Matthew Peters, Waleed Ammar. 2018b. Dissecting contextual word embeddings."},
        ]
        body = (
            "The fine-tuning approach, such as OpenAI GPT (Radford et al., 2018), introduces minimal task-specific parameters. "
            "ELMo (Peters et al., 2018) advances the state of the art for several benchmarks."
        )
        found = claims.find_citations(body, refs)
        # "Peters 2018" fits two references, so it is skipped rather than guessed.
        self.assertEqual([c["refs"] for c in found], [[1]])

    def test_claims_prefer_findings_and_single_citations(self):
        citations = [
            {"sentence": "We use the method of [1] as is in all experiments here.", "refs": [1]},
            {"sentence": "Bengio et al. showed that gradients vanish in long sequences [1].", "refs": [1]},
            {"sentence": "Many works [1, 2, 3] study this topic in detail.", "refs": [1, 2, 3]},
            {"sentence": "Bishop introduced a probabilistic view of networks [2].", "refs": [2]},
        ]
        chosen = claims.select_claims(citations, {1, 2})
        self.assertEqual(chosen[0]["sentence"], "Bengio et al. showed that gradients vanish in long sequences [1].")
        self.assertEqual({c["ref"] for c in chosen}, {1, 2})
        self.assertEqual(len(chosen), 3)  # "[1, 2, 3]" is background, not a claim

    def test_verdict_parsing_tolerates_extra_text_and_synonyms(self):
        reply = 'Here you go:\n[{"id": 1, "verdict": "Supported", "reason": "ok"}, {"id": 2, "verdict": "unclear"}, {"id": 9, "verdict": "supported"}]'
        parsed = claims._parse_verdicts(reply, 2)
        self.assertEqual({k: v["verdict"] for k, v in parsed.items()}, {1: "supported", 2: "cannot_tell"})

    def test_inverted_index_abstract(self):
        self.assertEqual(claims._from_inverted_index({"Deep": [0], "nets": [1, 3], "train": [2]}), "Deep nets train nets")


class IntegrityEndpointTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[current_user] = lambda: CurrentUser(id="u1")
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def _call(self, db, method, path, **body):
        with mock.patch.object(integrity, "get_supabase", return_value=db):
            if method == "get":
                return self.client.get(path)
            return self.client.post(path, json={"paper_id": "p1", **body})

    def test_link_check_saves_beside_the_reference_report(self):
        refs = [{"index": 1, "raw": "a", "status": "verified", "similarity": 1.0}]
        db = _FakeSupabase({
            "papers": [{**_paper(), "raw_text": "Code is available at https://a.org/x.\nReferences\n[1] a"}],
            "integrity_reports": [{"paper_id": "p1", "report_json": {"items": refs, "notices_checked": True},
                                   "generated_at": "2026-11-01T00:00:00+00:00"}],
        })

        async def fake_check(found):
            return [{**link, "status": "broken", "code": 404, "note": "gone"} for link in found]

        with mock.patch.object(integrity.link_check, "check_links", fake_check):
            body = self._call(db, "post", "/integrity/links").json()
        self.assertEqual((body["total"], body["broken"]), (1, 1))
        self.assertEqual(body["statements"][0]["kind"], "public")
        _, row = db.upserts[-1]
        self.assertEqual(row["report_json"]["items"], refs)  # the reference check is kept
        self.assertEqual(row["generated_at"], "2026-11-01T00:00:00+00:00")

    def test_saved_link_check_is_empty_until_run(self):
        db = _FakeSupabase({"papers": [_paper()]})
        self.assertEqual(self._call(db, "get", "/integrity/links/p1").status_code, 204)

    def test_link_report_alone_does_not_look_like_a_reference_check(self):
        db = _FakeSupabase({
            "papers": [_paper()],
            "integrity_reports": [{"paper_id": "p1", "report_json": {"links_check": {"links": []}}}],
        })
        self.assertEqual(self._call(db, "get", "/integrity/references/p1").status_code, 204)

    def test_claim_check_needs_the_reference_check_first(self):
        db = _FakeSupabase({"papers": [_paper()]})
        response = self._call(db, "post", "/integrity/claims")
        self.assertEqual(response.status_code, 409)
        self.assertIn("references first", response.json()["detail"])

    def test_claim_check_runs_and_saves(self):
        refs = [
            {"index": 1, "raw": "[1] Y. Bengio. Learning long-term dependencies. 1994.", "status": "verified",
             "similarity": 1.0, "matched_doi": "10.1/a", "matched_title": "Learning long-term dependencies"},
            {"index": 2, "raw": "[2] B. Other. Something. 1995.", "status": "verified", "similarity": 1.0, "matched_doi": "10.1/b"},
            {"index": 3, "raw": "[3] C. Third. Else. 1996.", "status": "not_found", "similarity": 0.1},
        ]
        paper = {**_paper(), "raw_text": (
            "1 Introduction\nRecurrent networks were shown to struggle with long-term dependencies [1]. "
            "Third work found something else entirely [3].\nReferences\n" + "\n".join(r["raw"] for r in refs))}
        db = _FakeSupabase({
            "papers": [paper],
            "integrity_reports": [{"paper_id": "p1", "report_json": {"items": refs, "notices_checked": True}}],
        })

        async def fake_abstracts(items, *_):
            return {item["index"]: {"title": "Learning long-term dependencies", "abstract": "Gradient descent struggles to learn long-term dependencies.", "source": "OpenAlex"} for item in items}

        async def fake_llm(system, user, **_):
            self.assertIn("long-term dependencies", user)
            return '[{"id": 1, "verdict": "supported", "reason": "The abstract says this."}]'

        with mock.patch.object(integrity.claim_check, "fetch_abstracts", fake_abstracts), \
                mock.patch.object(claims, "call_openrouter", fake_llm):
            body = self._call(db, "post", "/integrity/claims").json()
        self.assertEqual((body["total"], body["supported"], body["citing_sentences"]), (1, 1, 2))
        self.assertEqual(body["claims"][0]["ref"], 1)
        self.assertEqual(body["claims"][0]["abstract_source"], "OpenAlex")
        _, row = db.upserts[-1]
        self.assertIn("claims_check", row["report_json"])
        self.assertEqual(row["report_json"]["items"], refs)

    def test_claim_check_reports_when_the_ai_is_down(self):
        refs = [{"index": 1, "raw": "[1] Y. Bengio. Learning. 1994.", "status": "verified", "similarity": 1.0, "matched_doi": "10.1/a"}]
        paper = {**_paper(), "raw_text": "Recurrent networks were shown to struggle with long-term dependencies [1].\nReferences\n[1] Y. Bengio. Learning. 1994."}
        db = _FakeSupabase({"papers": [paper], "integrity_reports": [{"paper_id": "p1", "report_json": {"items": refs}}]})

        async def fake_abstracts(items, *_):
            return {1: {"title": "t", "abstract": "a" * 100, "source": "arXiv"}}

        async def down(*_, **__):
            raise claims.LLMRequestError("all models busy")

        with mock.patch.object(integrity.claim_check, "fetch_abstracts", fake_abstracts), \
                mock.patch.object(claims, "call_openrouter", down):
            response = self._call(db, "post", "/integrity/claims")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(db.upserts, [])

    def test_retraction_notices_are_added_to_an_older_saved_report(self):
        refs = [{"index": 1, "raw": "[1] A. Wakefield. Ileal-lymphoid-nodular hyperplasia. 1998.", "status": "verified",
                 "similarity": 1.0, "matched_doi": "10.1016/S0140-6736(97)11096-0"}]
        db = _FakeSupabase({"papers": [_paper()], "integrity_reports": [{"paper_id": "p1", "report_json": {"items": refs}}]})
        notice = {"type": "retraction", "label": "Retraction", "date": "2010-02-06", "notice_doi": "10.x/n", "source": "Retraction Watch"}

        async def fake_notices(dois, mailto=""):
            self.assertEqual(dois, ["10.1016/S0140-6736(97)11096-0"])
            return {"10.1016/s0140-6736(97)11096-0": [notice]}, True

        async def fail_verify_all(*_, **__):
            raise AssertionError("settled references must not be checked again")

        with mock.patch.object(integrity, "find_notices", fake_notices), mock.patch.object(integrity, "verify_all", fail_verify_all):
            body = self._call(db, "post", "/integrity/references").json()
        self.assertEqual((body["retracted"], body["notices_checked"]), (1, True))
        self.assertEqual(body["items"][0]["notices"][0]["type"], "retraction")


if __name__ == "__main__":
    unittest.main()
