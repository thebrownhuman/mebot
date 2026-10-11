"""Ollama client: model discovery + streaming chat (behaviour unchanged from prototype)."""

import json
from collections.abc import AsyncIterator

import httpx

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
