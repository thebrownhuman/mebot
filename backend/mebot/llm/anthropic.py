"""Anthropic Messages API (/v1/messages, SSE)."""

import json
from collections.abc import AsyncIterator

from mebot.llm.base import HttpAdapter, TestResult, Usage

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
        prompt = completion = None
        async for line in self._stream_lines("/v1/messages", payload):
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except ValueError:
                continue
            kind = event.get("type")
            if kind == "content_block_delta":
                text = (event.get("delta") or {}).get("text")
                if text:
                    yield text
            elif kind == "message_start":
                usage = (event.get("message") or {}).get("usage") or {}
                prompt = usage.get("input_tokens", prompt)
                completion = usage.get("output_tokens", completion)
            elif kind == "message_delta":
                completion = (event.get("usage") or {}).get("output_tokens", completion)
            if prompt is not None and completion is not None:
                self.usage = Usage(int(prompt), int(completion))

    async def test(self, *, model: str) -> TestResult:
        payload = self._payload([{"role": "user", "content": "ping"}], model, None, 1, stream=False)
        return await self._timed(self._post_json("/v1/messages", payload))

    async def list_models(self) -> list[str]:
        try:
            data = await self._get_json("/v1/models")
            return sorted(m["id"] for m in data.get("data", []) if m.get("id"))
        except Exception:  # noqa: BLE001 - best effort
            return []
