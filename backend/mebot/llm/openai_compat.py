"""OpenAI-style /chat/completions (OpenAI, OpenRouter, Groq, Gemini compat, custom)."""

import json
from collections.abc import AsyncIterator

from mebot.llm.base import HttpAdapter, TestResult, Usage


class OpenAICompatClient(HttpAdapter):
    # Ask for a final usage chunk. Off for custom servers, which may reject the field.
    include_usage = True
    # Off for providers with no embeddings endpoint (Groq); set by the factory.
    supports_embeddings = True

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
        if self.include_usage:
            payload["stream_options"] = {"include_usage": True}
        async for line in self._stream_lines("/chat/completions", payload):
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
            except ValueError:
                continue
            usage = event.get("usage")
            if isinstance(usage, dict):
                self.usage = Usage(
                    int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
                )
            choices = event.get("choices") or []
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

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        if not self.supports_embeddings:
            return await super().embed(texts, model=model)
        data = await self._post_json("/embeddings", {"model": model, "input": texts}, timeout=60.0)
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            return self._check_vectors(texts, [])
        rows = sorted(rows, key=lambda r: r.get("index", 0))
        usage = data.get("usage") or {}
        tokens = usage.get("prompt_tokens") or usage.get("total_tokens")
        self.embed_tokens = int(tokens) if tokens else None
        return self._check_vectors(texts, [r.get("embedding") for r in rows])

    async def list_models(self) -> list[str]:
        try:
            data = await self._get_json("/models")
            return sorted(m["id"] for m in data.get("data", []) if m.get("id"))
        except Exception:  # noqa: BLE001 - best effort
            return []
