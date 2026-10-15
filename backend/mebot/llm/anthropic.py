"""Anthropic Messages API (/v1/messages, SSE)."""

import json
from collections.abc import AsyncIterator

from mebot.llm.base import HttpAdapter, TestResult

API_VERSION = "2023-06-01"


def _split_system(messages: list[dict]) -> tuple[str | None, list[dict]]:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system") or None
    return system, [m for m in messages if m["role"] != "system"]


class AnthropicClient(HttpAdapter):
    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key or "", "anthropic-version": API_VERSION}

    def _payload(self, messages, model, temperature, max_tokens, stream) -> dict:
        system, rest = _split_system(messages)
        payload: dict = {"model": model}
        if system:
            payload["system"] = system
        payload["messages"] = rest
        payload["stream"] = stream
        if temperature is not None:
            payload["temperature"] = temperature
        payload["max_tokens"] = max_tokens
        return payload

    async def stream_chat(
        self, messages: list[dict], *, model: str, temperature: float, max_tokens: int
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, model, temperature, max_tokens, True)
        async for line in self._stream_lines("/v1/messages", payload):
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except ValueError:
                continue
            if event.get("type") == "content_block_delta":
                text = (event.get("delta") or {}).get("text")
                if text:
                    yield text

    async def test(self, *, model: str) -> TestResult:
        payload = self._payload([{"role": "user", "content": "ping"}], model, None, 1, stream=False)
        return await self._timed(self._post_json("/v1/messages", payload))

    async def list_models(self) -> list[str]:
        try:
            data = await self._get_json("/v1/models")
            return sorted(m["id"] for m in data.get("data", []) if m.get("id"))
        except Exception:  # noqa: BLE001 - best effort
            return []
