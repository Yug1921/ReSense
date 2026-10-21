import os
import unittest
from types import SimpleNamespace
from unittest import mock

for _name in ("SUPABASE_URL", "SUPABASE_KEY", "OPENROUTER_API_KEY"):
    os.environ.setdefault(_name, "test")

import anthropic
import httpx

from app.services import llm


def _message(text="A summary.", stop_reason="end_turn"):
    content = [SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(content=content, stop_reason=stop_reason)


class _FakeClaude:
    def __init__(self, result):
        self.calls = []
        self.messages = self
        self._result = result

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _free_chain_reply(text="Free answer."):
    async def fake_post(payload, base_url=None, api_key=None):
        return {"choices": [{"message": {"content": text}}]}
    return fake_post


class ClaudeFirstTests(unittest.IsolatedAsyncioTestCase):
    def _patch(self, key, claude, free=None):
        patches = [
            mock.patch.object(llm.settings, "anthropic_api_key", key),
            mock.patch.object(llm, "_claude", lambda: claude),
            mock.patch.object(llm, "_post_chat_completion", free or _free_chain_reply()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    async def test_claude_answers_when_key_is_set(self):
        claude = _FakeClaude(_message("Claude summary."))
        self._patch("sk-test", claude)
        self.assertEqual(await llm.call_openrouter("sys", "user", max_tokens=900), "Claude summary.")
        call = claude.calls[0]
        self.assertEqual(call["model"], llm.settings.anthropic_model)
        self.assertEqual(call["system"], "sys")
        self.assertNotIn("temperature", call)  # Haiku 5.5 rejects non-default sampling settings

    async def test_without_key_claude_is_not_called(self):
        claude = _FakeClaude(_message())
        self._patch("", claude)
        self.assertEqual(await llm.call_openrouter("sys", "user"), "Free answer.")
        self.assertEqual(claude.calls, [])

    async def test_claude_error_falls_back_to_free_providers(self):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        error = anthropic.APIStatusError(
            "overloaded", response=httpx.Response(529, request=request), body=None
        )
        self._patch("sk-test", _FakeClaude(error))
        self.assertEqual(await llm.call_openrouter("sys", "user"), "Free answer.")

    async def test_refusal_falls_back_to_free_providers(self):
        self._patch("sk-test", _FakeClaude(_message("", stop_reason="refusal")))
        self.assertEqual(await llm.call_openrouter("sys", "user"), "Free answer.")

    async def test_everything_failing_raises_friendly_error(self):
        async def failing_post(payload, base_url=None, api_key=None):
            raise llm.LLMRequestError("free provider down")
        self._patch("sk-test", _FakeClaude(_message("", stop_reason="max_tokens")), failing_post)
        with self.assertRaises(llm.LLMRequestError):
            await llm.call_openrouter("sys", "user")
