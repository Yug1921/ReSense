import asyncio
import time
import unittest
from unittest import mock

import httpx

from app.services import references as R


def _paced_client(handler, pacers):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10)
    R._CLIENT_PACERS[client] = pacers
    return client


class ProviderPacingTests(unittest.IsolatedAsyncioTestCase):
    async def test_pacer_limits_concurrency_and_spacing(self):
        starts, inflight, peak = [], [0], [0]

        async def handler(request):
            starts.append(time.monotonic())
            inflight[0] += 1
            peak[0] = max(peak[0], inflight[0])
            await asyncio.sleep(0.01)
            inflight[0] -= 1
            return httpx.Response(200, json={}, request=request)

        pacers = {"api.crossref.org": R._HostPacer(1, 0.05)}
        async with _paced_client(handler, pacers) as client:
            await asyncio.gather(
                *(R._get_with_retries(client, f"{R._CROSSREF_URL}/works") for _ in range(4))
            )
        self.assertEqual(peak[0], 1)
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        self.assertTrue(all(gap >= 0.045 for gap in gaps), gaps)

    async def test_429_retry_after_pauses_all_workers_then_succeeds(self):
        calls = []

        def handler(request):
            calls.append(time.monotonic())
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": "0.2"}, request=request)
            return httpx.Response(200, json={}, request=request)

        pacer = R._HostPacer(3, 0.0)
        async with _paced_client(handler, {"api.crossref.org": pacer}) as client:
            first = await R._get_with_retries(client, f"{R._CROSSREF_URL}/works")
            # A second worker arriving during the cooldown must wait it out too.
            second = await R._get_with_retries(client, f"{R._CROSSREF_URL}/works")
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertGreaterEqual(calls[1] - calls[0], 0.19)
        self.assertGreaterEqual(calls[2] - calls[0], 0.19)

    async def test_retries_are_bounded_and_end_unavailable(self):
        calls = []

        def handler(request):
            calls.append(request)
            if request.url.host == "api.crossref.org":
                return httpx.Response(429, request=request)
            return httpx.Response(200, json={"results": []}, request=request)

        with mock.patch.object(R.asyncio, "sleep", new=mock.AsyncMock()):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                result = await R.verify_reference(
                    client, "A. Author. A study of things. Some Journal, 2020.", ""
                )
        crossref_calls = [c for c in calls if c.url.host == "api.crossref.org"]
        self.assertEqual(len(crossref_calls), R._MAX_ATTEMPTS)
        self.assertEqual(result["status"], "unavailable")

    async def test_empty_mailto_is_not_sent_to_crossref(self):
        seen = []

        def handler(request):
            seen.append(request.url)
            if request.url.host == "api.crossref.org":
                return httpx.Response(200, json={"message": {"items": []}}, request=request)
            return httpx.Response(200, json={"results": []}, request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await R.verify_reference(client, "A. Author. A study of things. 2020.", "")
        crossref = [u for u in seen if u.host == "api.crossref.org"]
        self.assertTrue(crossref)
        self.assertNotIn("mailto", crossref[0].params)

    def test_polite_pool_gets_higher_crossref_limits(self):
        public = R._provider_pacers(polite=False)["api.crossref.org"]
        polite = R._provider_pacers(polite=True)["api.crossref.org"]
        self.assertEqual(public._min_interval, 1.0)
        self.assertLess(polite._min_interval, public._min_interval)
