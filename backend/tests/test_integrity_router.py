import os
import unittest
from unittest import mock

# Settings() reads required env vars at import time; give it dummies so the
# app imports without a real .env. No network or database is touched.
for _name in ("SUPABASE_URL", "SUPABASE_KEY", "OPENROUTER_API_KEY"):
    os.environ.setdefault(_name, "test")

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.routers import integrity
from app.services import references


class _Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters = db, table, {}

    def select(self, *_):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def limit(self, _):
        return self

    def upsert(self, row, on_conflict=None):
        self.db.upserts.append((self.table, row))
        return self

    def execute(self):
        rows = [
            row for row in self.db.rows.get(self.table, [])
            if all(row.get(k) == v for k, v in self.filters.items())
        ]
        return mock.Mock(data=rows)


class _FakeSupabase:
    def __init__(self, rows):
        self.rows, self.upserts = rows, []

    def table(self, name):
        return _Query(self, name)


def _paper(status="ready"):
    return {
        "id": "p1",
        "status": status,
        "raw_text": "References\n[1] A. Author. Some title. 2020.\n[2] B. Author. Other title. 2021.",
        "structure_json": {},
    }


class IntegrityRouterTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def _post(self, db, **body):
        with mock.patch.object(integrity, "get_supabase", return_value=db):
            return self.client.post("/integrity/references", json={"paper_id": "p1", **body})

    def test_missing_paper_returns_404(self):
        self.assertEqual(self._post(_FakeSupabase({})).status_code, 404)

    def test_paper_not_ready_returns_409(self):
        db = _FakeSupabase({"papers": [_paper(status="parsing")]})
        self.assertEqual(self._post(db).status_code, 409)

    def test_fresh_report_counts_match_items_and_is_cached(self):
        db = _FakeSupabase({"papers": [_paper()]})
        items = [
            {"index": 1, "raw": "a", "status": "verified", "similarity": 1.0,
             "source": "crossref", "publication_relation": "exact", "title_score": 1.0},
            {"index": 2, "raw": "b", "status": "unavailable", "similarity": 0.0,
             "error": "Crossref returned 429"},
        ]

        async def fake_verify_all(refs, mailto, **_):
            return items

        with mock.patch.object(integrity, "verify_all", fake_verify_all):
            response = self._post(db)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual((body["total"], body["verified"], body["unavailable"]), (2, 1, 1))
        self.assertFalse(body["cached"])
        self.assertEqual(body["items"][0]["source"], "crossref")
        self.assertEqual(body["items"][0]["publication_relation"], "exact")
        self.assertEqual(body["items"][1]["conflict_fields"], [])
        table, row = db.upserts[0]
        self.assertEqual(table, "integrity_reports")
        self.assertNotIn("cached", row["report_json"])
        self.assertIn("generated_at", row)

    def test_cached_report_is_returned_without_verifying(self):
        cached_items = [{"index": 1, "raw": "a", "status": "not_found", "similarity": 0.1}]
        db = _FakeSupabase({
            "papers": [_paper()],
            "integrity_reports": [{"paper_id": "p1", "report_json": {"items": cached_items}}],
        })

        async def fail_verify_all(refs, mailto, **_):
            raise AssertionError("verify_all should not run for a cached report")

        with mock.patch.object(integrity, "verify_all", fail_verify_all):
            body = self._post(db).json()
        self.assertTrue(body["cached"])
        self.assertEqual((body["total"], body["not_found"]), (1, 1))
        self.assertEqual(db.upserts, [])

    def test_cached_report_rechecks_only_unavailable_items(self):
        cached_items = [
            {"index": 1, "raw": "a", "status": "verified", "similarity": 1.0},
            {"index": 2, "raw": "b", "status": "unavailable", "similarity": 0.0,
             "error": "OpenAlex returned 429"},
        ]
        db = _FakeSupabase({
            "papers": [_paper()],
            "integrity_reports": [{"paper_id": "p1", "report_json": {"items": cached_items}}],
        })
        seen = []

        async def fake_verify_all(refs, mailto, **_):
            seen.append(refs)
            return [{"index": 1, "raw": "b", "status": "verified", "similarity": 0.95,
                     "source": "openalex"}]

        with mock.patch.object(integrity, "verify_all", fake_verify_all):
            body = self._post(db).json()
        self.assertEqual(seen, [["b"]])
        self.assertEqual([i["index"] for i in body["items"]], [1, 2])
        self.assertEqual((body["verified"], body["unavailable"]), (2, 0))
        self.assertEqual(body["items"][1]["source"], "openalex")
        self.assertEqual(len(db.upserts), 1)


class VerifyAllTests(unittest.IsolatedAsyncioTestCase):
    async def test_unexpected_error_keeps_index_and_other_results(self):
        async def fake_verify_reference(client, ref_text, mailto):
            if ref_text == "boom":
                raise RuntimeError("parser bug")
            return {"raw": ref_text, "status": "verified", "similarity": 1.0}

        with mock.patch.object(references, "verify_reference", fake_verify_reference):
            results = await references.verify_all(["ok", "boom", "ok2"], "")
        self.assertEqual([r["index"] for r in results], [1, 2, 3])
        self.assertEqual([r["status"] for r in results], ["verified", "unavailable", "verified"])

    async def test_http_error_result_is_valid_report_item(self):
        async def fake_verify_reference(client, ref_text, mailto):
            raise httpx.ConnectError("down")

        with mock.patch.object(references, "verify_reference", fake_verify_reference):
            results = await references.verify_all(["x"], "")
        integrity._build_response("p1", results, cached=False)  # must not raise
        self.assertEqual(results[0]["index"], 1)
