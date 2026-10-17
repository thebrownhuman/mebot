"""Ollama (/api/chat, NDJSON stream). Sends think:false so Gemma-style reasoning can't
leak into replies."""

import json
from collections.abc import AsyncIterator

from mebot.llm.base import HttpAdapter, TestResult, Usage


class OllamaClient(HttpAdapter):
    # Set when the model emitted "thinking" despite think:false; chat logs a warning.
    leaked_thinking = False

    def _payload(self, messages, model, temperature, max_tokens, stream) -> dict:
        return {
            "model": model,
            "messages": messages,
            "think": False,
            "stream": stream,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }

    async def stream_chat(
        self, messages: list[dict], *, model: str, temperature: float, max_tokens: int
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, model, temperature, max_tokens, True)
        async for line in self._stream_lines("/api/chat", payload):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("done") and "eval_count" in event:
                self.usage = Usage(
                    int(event.get("prompt_eval_count") or 0), int(event.get("eval_count") or 0)
                )
            msg = event.get("message") or {}
            if msg.get("thinking"):
                self.leaked_thinking = True
            chunk = msg.get("content", "")
            if chunk:
                yield chunk

    async def test(self, *, model: str) -> TestResult:
        payload = self._payload([{"role": "user", "content": "ping"}], model, 0, 1, False)
        return await self._timed(self._post_json("/api/chat", payload))

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        data = await self._post_json("/api/embed", {"model": model, "input": texts}, timeout=60.0)
        vectors = data.get("embeddings") if isinstance(data, dict) else None
        tokens = data.get("prompt_eval_count") if isinstance(data, dict) else None
        self.embed_tokens = int(tokens) if tokens else None
        return self._check_vectors(texts, vectors if isinstance(vectors, list) else [])

    async def list_models(self) -> list[str]:
        try:
            data = await self._get_json("/api/tags")
            return [m["name"].replace(":latest", "") for m in data.get("models", [])]
        except Exception:  # noqa: BLE001 - best effort
            return []
