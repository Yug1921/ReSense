import os
import unittest
from unittest import mock

for _name in ("SUPABASE_URL", "SUPABASE_KEY", "OPENROUTER_API_KEY"):
    os.environ.setdefault(_name, "test")

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth
from app.auth import CurrentUser, current_user
from app.main import app
from app.routers import papers, session


class _Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.deleting = db, table, {}, False

    def select(self, *_):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def limit(self, _):
        return self

    def order(self, *_, **__):
        return self

    def delete(self):
        self.deleting = True
        return self

    def execute(self):
        rows = [
            row for row in self.db.rows.get(self.table, [])
            if all(row.get(k) == v for k, v in self.filters.items())
        ]
        if self.deleting:
            self.db.rows[self.table] = [r for r in self.db.rows.get(self.table, []) if r not in rows]
        return mock.Mock(data=rows)


class _FakeSupabase:
    def __init__(self, rows):
        self.rows = rows
        self.storage = mock.Mock()

    def table(self, name):
        return _Query(self, name)


def _db():
    return _FakeSupabase({
        "papers": [
            {"id": "mine", "user_id": "u1", "filename": "resnet.pdf", "status": "ready",
             "uploaded_at": "2026-10-21T10:00:00+00:00", "word_count": 7640, "structure_json": {}},
            {"id": "theirs", "user_id": "u2", "filename": "bert.pdf", "status": "ready",
             "uploaded_at": "2026-10-21T11:00:00+00:00", "word_count": 5000, "structure_json": {}},
        ],
        "figures": [{"paper_id": "mine", "storage_path": "mine/page1_0.png"}],
    })


class PaperLibraryTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[current_user] = lambda: CurrentUser(id="u1")
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def test_list_shows_only_my_papers(self):
        with mock.patch.object(papers, "get_supabase", return_value=_db()):
            response = self.client.get("/papers")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([p["paper_id"] for p in response.json()], ["mine"])
        self.assertEqual(response.json()[0]["word_count"], 7640)

    def test_cannot_open_or_delete_someone_elses_paper(self):
        db = _db()
        with mock.patch.object(session, "get_supabase", return_value=db):
            self.assertEqual(self.client.get("/session/theirs").status_code, 404)
        with mock.patch.object(papers, "get_supabase", return_value=db):
            self.assertEqual(self.client.delete("/papers/theirs").status_code, 404)
        self.assertEqual(len(db.rows["papers"]), 2)

    def test_delete_removes_paper_and_its_figure_images(self):
        db = _db()
        with mock.patch.object(papers, "get_supabase", return_value=db):
            self.assertEqual(self.client.delete("/papers/mine").status_code, 204)
        self.assertEqual([p["id"] for p in db.rows["papers"]], ["theirs"])
        db.storage.from_.return_value.remove.assert_called_once_with(["mine/page1_0.png"])

    def test_signed_out_requests_are_refused(self):
        app.dependency_overrides.clear()
        self.assertEqual(self.client.get("/papers").status_code, 401)
        self.assertEqual(self.client.get("/session/mine").status_code, 401)


class TokenLookupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        auth._token_cache.clear()
        self.calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            self.calls += 1
            self.assertTrue(request.url.path.endswith("/auth/v1/user"))
            if request.headers["Authorization"] == "Bearer good":
                return httpx.Response(200, json={"id": "u1", "email": "om@example.com"})
            return httpx.Response(401, json={"msg": "invalid JWT"})

        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient
        patcher = mock.patch.object(
            auth.httpx, "AsyncClient", lambda **kw: real_client(transport=transport, **kw)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        url_patcher = mock.patch.object(auth.settings, "supabase_url", "https://project.supabase.co")
        url_patcher.start()
        self.addCleanup(url_patcher.stop)

    async def test_valid_token_resolves_user_and_is_cached(self):
        first = await current_user("Bearer good")
        second = await current_user("Bearer good")
        self.assertEqual(first, CurrentUser(id="u1", email="om@example.com"))
        self.assertEqual(second, first)
        self.assertEqual(self.calls, 1)

    async def test_expired_token_is_401(self):
        with self.assertRaises(HTTPException) as caught:
            await current_user("Bearer stale")
        self.assertEqual(caught.exception.status_code, 401)

    async def test_missing_header_is_401_without_a_lookup(self):
        for header in (None, "", "Basic abc", "Bearer "):
            with self.assertRaises(HTTPException) as caught:
                await current_user(header)
            self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(self.calls, 0)


if __name__ == "__main__":
    unittest.main()
