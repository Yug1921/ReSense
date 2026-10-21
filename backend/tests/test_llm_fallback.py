import os
import unittest
from unittest import mock

for _name in ("SUPABASE_URL", "SUPABASE_KEY"):
    os.environ.setdefault(_name, "test")

from app.services import llm, providers

GEMINI_MODELS = [
    "models/gemini-2.5-pro", "models/gemini-2.5-flash", "models/gemini-2.5-flash-lite",
    "models/gemini-3-flash-preview", "models/gemini-3.1-flash-lite", "models/gemini-2.5-flash-image",
    "models/gemini-2.5-flash-preview-tts", "models/text-embedding-004", "models/gemini-3-pro-preview",
]
GROQ_MODELS = [
    "llama-3.1-8b-instant", "openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b",
    "whisper-large-v3", "meta-llama/llama-guard-4-12b", "openai/gpt-oss-safeguard-20b",
]
OPENROUTER_MODELS = [
    {"id": "nvidia/nemotron-3-super-120b-a12b:free", "context_length": 262144, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "google/gemma-4-31b-it:free", "context_length": 131072, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "some/tiny-model:free", "context_length": 8192, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "openai/gpt-5", "context_length": 400000, "pricing": {"prompt": "0.00000125", "completion": "0.00001"}},
    {"id": "openrouter/free", "context_length": 200000, "pricing": {"prompt": "0", "completion": "0"}},
]


class RankingTests(unittest.TestCase):
    def test_gemini_prefers_stable_flash_and_never_pro(self):
        ranked = providers.rank_gemini(GEMINI_MODELS)
        self.assertEqual(
            ranked,
            ["gemini-2.5-flash", "gemini-3-flash-preview", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite"],
        )

    def test_groq_prefers_big_models_and_skips_speech_and_guards(self):
        self.assertEqual(
            providers.rank_groq(GROQ_MODELS),
            ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b", "llama-3.1-8b-instant"],
        )

    def test_openrouter_keeps_only_free_long_context_models(self):
        self.assertEqual(
            providers.rank_openrouter(OPENROUTER_MODELS),
            ["nvidia/nemotron-3-super-120b-a12b:free", "google/gemma-4-31b-it:free"],
        )


def _ok(text):
    return {"choices": [{"message": {"content": text}}]}


class FallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        providers.reset()
        self.addCleanup(providers.reset)
        listed = {
            "gemini": providers.rank_gemini(GEMINI_MODELS),
            "groq": providers.rank_groq(GROQ_MODELS),
            "openrouter": providers.rank_openrouter(OPENROUTER_MODELS),
        }

        async def fake_list(provider, api_key):
            return listed[provider]

        for patch in (
            mock.patch.object(providers, "_list_models", fake_list),
            mock.patch.object(providers.settings, "gemini_api_key", "g"),
            mock.patch.object(providers.settings, "groq_api_key", "q"),
            mock.patch.object(providers.settings, "openrouter_api_key", "o"),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.calls = []

    def _respond(self, behaviour):
        async def fake_post(payload, base_url=None, api_key=None):
            self.calls.append(payload["model"])
            result = behaviour(payload["model"])
            if isinstance(result, Exception):
                raise result
            return result
        return mock.patch.object(llm, "_post_chat_completion", fake_post)

    async def test_first_working_model_answers(self):
        with self._respond(lambda model: _ok("hello")):
            self.assertEqual(await llm.call_openrouter("sys", "short question"), "hello")
        self.assertEqual(self.calls, ["gemini-2.5-flash"])

    async def test_falls_through_providers_until_one_works(self):
        def behaviour(model):
            if model.startswith("gemini"):
                return llm.LLMRateLimitError("Quota exceeded: GenerateRequestsPerDayPerProjectPerModel")
            if model == "openai/gpt-oss-120b":
                return llm.LLMProviderUnavailableError("503")
            return _ok("from groq")
        with self._respond(behaviour):
            self.assertEqual(await llm.call_openrouter("sys", "short question"), "from groq")
        self.assertEqual(self.calls[-1], "qwen/qwen3.8-27b")

    async def test_models_at_their_daily_limit_are_skipped_next_time(self):
        def behaviour(model):
            if model == "gemini-2.5-flash":
                return llm.LLMRateLimitError("Quota exceeded: GenerateRequestsPerDayPerProjectPerModel")
            return _ok("ok")
        with self._respond(behaviour):
            await llm.call_openrouter("sys", "q")
            self.calls.clear()
            await llm.call_openrouter("sys", "q")
        self.assertEqual(self.calls, ["gemini-3-flash-preview"])

    async def test_long_requests_skip_groq_free_plan(self):
        paper = "x" * 40_000  # about 10,000 tokens: over Groq's free per-minute allowance
        with self._respond(lambda model: llm.LLMRequestError("down")):
            with self.assertRaises(llm.LLMRequestError):
                await llm.call_openrouter("sys", paper, max_tokens=2200)
        self.assertFalse(any(m.startswith(("openai/", "qwen/", "llama")) for m in self.calls))
        self.assertIn("nvidia/nemotron-3-super-120b-a12b:free", self.calls)

    async def test_all_rate_limited_reports_rate_limit(self):
        with self._respond(lambda model: llm.LLMRateLimitError("slow down")):
            with self.assertRaises(llm.LLMRateLimitError):
                await llm.call_openrouter("sys", "q")

    async def test_reasoning_settings_only_where_supported(self):
        payloads = []

        async def fake_post(payload, base_url=None, api_key=None):
            payloads.append(payload)
            raise llm.LLMRequestError("down")

        with mock.patch.object(llm, "_post_chat_completion", fake_post):
            with self.assertRaises(llm.LLMRequestError):
                await llm.call_openrouter("sys", "q")
        by_model = {p["model"]: p for p in payloads}
        self.assertEqual(by_model["gemini-2.5-flash"]["reasoning_effort"], "low")
        self.assertEqual(by_model["qwen/qwen3.8-27b"]["reasoning_effort"], "none")
        self.assertEqual(by_model["nvidia/nemotron-3-super-120b-a12b:free"]["reasoning"]["effort"], "low")

    async def test_pinned_model_from_env_is_tried_first(self):
        with mock.patch.object(providers.settings, "gemini_model", "gemini-custom"):
            with self._respond(lambda model: _ok("pinned")):
                await llm.call_openrouter("sys", "q")
        self.assertEqual(self.calls, ["gemini-custom"])

    async def test_no_keys_gives_clear_message(self):
        with mock.patch.object(providers.settings, "gemini_api_key", ""), \
             mock.patch.object(providers.settings, "groq_api_key", ""), \
             mock.patch.object(providers.settings, "openrouter_api_key", ""):
            with self.assertRaisesRegex(llm.LLMRequestError, "add a Gemini, Groq or OpenRouter key"):
                await llm.call_openrouter("sys", "q")


class ChosenProviderTests(FallbackTests):
    async def test_choice_limits_to_that_provider(self):
        token = providers.chosen_provider.set("openrouter")
        self.addCleanup(providers.chosen_provider.reset, token)
        with self._respond(lambda model: llm.LLMRequestError("down") if "nemotron" in model else _ok("ok")):
            self.assertEqual(await llm.call_openrouter("sys", "q"), "ok")
        self.assertTrue(all(m.endswith(":free") for m in self.calls))

    async def test_groq_choice_explains_long_requests(self):
        token = providers.chosen_provider.set("groq")
        self.addCleanup(providers.chosen_provider.reset, token)
        with self.assertRaisesRegex(llm.LLMRequestError, "too long for Groq"):
            await llm.call_openrouter("sys", "x" * 40_000, max_tokens=2200)

    def test_safety_models_are_never_picked(self):
        ranked = providers.rank_openrouter(
            [{"id": "nvidia/nemotron-3.5-content-safety:free", "context_length": 128000, "pricing": {}}]
        )
        self.assertEqual(ranked, [])

    def test_header_sets_choice_for_one_request(self):
        from fastapi.testclient import TestClient
        from app.main import app
        seen = []

        @app.get("/_test_choice")
        def _probe():
            seen.append(providers.chosen_provider.get())
            return {}

        client = TestClient(app)
        client.get("/_test_choice", headers={"X-AI-Provider": "Groq"})
        client.get("/_test_choice", headers={"X-AI-Provider": "nonsense"})
        client.get("/_test_choice")
        self.assertEqual(seen, ["groq", "auto", "auto"])
