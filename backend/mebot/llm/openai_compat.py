"""OpenAI-style /chat/completions (OpenAI, OpenRouter, Groq, Gemini compat, custom)."""

import json
from collections.abc import AsyncIterator

from mebot.llm.base import HttpAdapter, TestResult


class OpenAICompatClient(HttpAdapter):
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def stream_chat(
        self, messages: list[dict], *, model: str, temperature: float, max_tokens: int
    ) -> AsyncIterator[str]:
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        async for line in self._stream_lines("/chat/completions", payload):
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                choices = json.loads(data).get("choices") or []
            except ValueError:
                continue
            chunk = (choices[0].get("delta") or {}).get("content") if choices else None
            if chunk:
                yield chunk

    async def test(self, *, model: str) -> TestResult:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "stream": False,
            "max_tokens": 1,
        }
        return await self._timed(self._post_json("/chat/completions", payload))

    async def list_models(self) -> list[str]:
        try:
            data = await self._get_json("/models")
            return sorted(m["id"] for m in data.get("data", []) if m.get("id"))
        except Exception:  # noqa: BLE001 - best effort
            return []
