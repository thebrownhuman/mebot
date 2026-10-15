"""Ollama (/api/chat, NDJSON stream). Sends think:false so Gemma-style reasoning can't
leak into replies."""

import json
from collections.abc import AsyncIterator

from mebot.llm.base import HttpAdapter, TestResult


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
                msg = json.loads(line).get("message") or {}
            except ValueError:
                continue
            if msg.get("thinking"):
                self.leaked_thinking = True
            chunk = msg.get("content", "")
            if chunk:
                yield chunk

    async def test(self, *, model: str) -> TestResult:
        payload = self._payload([{"role": "user", "content": "ping"}], model, 0, 1, False)
        return await self._timed(self._post_json("/api/chat", payload))

    async def list_models(self) -> list[str]:
        try:
            data = await self._get_json("/api/tags")
            return [m["name"].replace(":latest", "") for m in data.get("models", [])]
        except Exception:  # noqa: BLE001 - best effort
            return []


# --- legacy module API, still used by routes/chat.py and routes/health.py ----------
# TODO(llm-provider): removed once chat uses the configured provider.

import httpx  # noqa: E402

FALLBACK_MODEL = "gemma4:e2b-it-qat"
GEN_OPTIONS = {"temperature": 0.4, "top_p": 0.95, "top_k": 64}


async def list_models(host: str) -> list[str]:
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.get(f"{host}/api/tags")
        r.raise_for_status()
        return [m["name"].replace(":latest", "") for m in r.json().get("models", [])]


async def health(host: str, preferred_model: str) -> dict:
    """Report whether Ollama is reachable and which model will be used."""
    try:
        names = await list_models(host)
    except Exception as e:  # noqa: BLE001 - any failure means "not reachable"
        return {"ollama": False, "model": None, "message": str(e) or type(e).__name__}
    if preferred_model in names:
        return {"ollama": True, "model": preferred_model}
    if any(n.startswith(FALLBACK_MODEL) for n in names):
        return {"ollama": True, "model": FALLBACK_MODEL}
    return {"ollama": True, "model": None, "message": f"No suitable model. Pull {FALLBACK_MODEL}."}


def build_payload(model: str, messages: list[dict]) -> dict:
    return {
        "model": model,
        "messages": messages,
        "think": False,  # keep Gemma 4 thinking OFF — it would leak into replies
        "stream": True,
        "options": GEN_OPTIONS,
    }


async def stream_chat(host: str, payload: dict) -> AsyncIterator[str]:
    """Yield content chunks from Ollama's streaming /api/chat."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=600)) as client:
        async with client.stream("POST", f"{host}/api/chat", json=payload) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                msg = json.loads(line).get("message", {})
                if msg.get("thinking"):
                    payload.setdefault("_leaked_thinking", True)
                chunk = msg.get("content", "")
                if chunk:
                    yield chunk
