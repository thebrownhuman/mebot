"""Provider-neutral LLM client interface, errors and HTTP helpers.

Every message that can reach a user or a log goes through ``scrub`` so an API key
echoed back by a provider (some reflect request headers in error bodies) never leaks.
"""

import json
import time
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

TEST_TIMEOUT = 10.0
STREAM_TIMEOUT = httpx.Timeout(10.0, read=120.0)
MAX_PROVIDER_MESSAGE = 200

ErrorKind = Literal[
    "auth", "rate_limit", "model", "bad_request", "provider", "timeout", "unreachable"
]


@dataclass
class TestResult:
    ok: bool
    latency_ms: int


@dataclass(frozen=True)
class Usage:
    """Token usage as reported by the provider for one streamed reply."""

    prompt_tokens: int
    completion_tokens: int

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMError(Exception):
    """A provider call failed. ``message`` is safe to show the owner (key scrubbed)."""

    def __init__(self, kind: ErrorKind, message: str, status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status = status


class LLMClient(Protocol):
    def stream_chat(
        self, messages: list[dict], *, model: str, temperature: float, max_tokens: int
    ) -> AsyncIterator[str]: ...

    async def test(self, *, model: str) -> TestResult: ...

    async def list_models(self) -> list[str]: ...


def scrub(text: str, secrets: Iterable[str | None]) -> str:
    for s in secrets:
        if s and len(s) >= 4:
            text = text.replace(s, "[redacted]")
    return text


def _provider_reason(body: str) -> str:
    try:
        data = json.loads(body)
    except ValueError:
        return body.strip()[:MAX_PROVIDER_MESSAGE]
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        err = data.get("error", data)
        if isinstance(err, dict):
            msg = err.get("message") or err.get("error") or ""
        else:
            msg = err
        return str(msg).strip()[:MAX_PROVIDER_MESSAGE]
    return ""


def error_from_status(name: str, status: int, body: str, secrets: Iterable[str | None]) -> LLMError:
    reason = scrub(_provider_reason(body), secrets)
    suffix = f": {reason}" if reason else ""
    if status in (401, 403):
        return LLMError("auth", f"{name} rejected the API key ({status}){suffix}", status)
    if status == 404:
        return LLMError("model", f"{name} could not find that model ({status}){suffix}", status)
    if status == 429:
        return LLMError(
            "rate_limit", f"{name} rate limited the request, try again shortly.", status
        )
    if status >= 500:
        return LLMError("provider", f"{name} returned a server error ({status}){suffix}", status)
    return LLMError("bad_request", f"{name} rejected the request ({status}){suffix}", status)


def error_from_exception(name: str, base_url: str, exc: Exception) -> LLMError:
    if isinstance(exc, httpx.TimeoutException):
        return LLMError("timeout", f"Timed out contacting {name}.")
    if isinstance(exc, httpx.ConnectError):
        return LLMError("unreachable", f"Cannot reach {name} at {base_url}.")
    return LLMError("unreachable", f"Error contacting {name} ({type(exc).__name__}).")


class HttpAdapter:
    """Shared plumbing: name/base_url/key, error mapping, timed tiny test call."""

    name: str

    def __init__(self, name: str, base_url: str, api_key: str | None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or None
        # Set by stream_chat when the provider reports token usage; None otherwise.
        self.usage: Usage | None = None

    def _headers(self) -> dict[str, str]:
        return {}

    async def _check(self, r: httpx.Response) -> None:
        if r.status_code >= 400:
            body = (await r.aread()).decode("utf-8", "replace")
            raise error_from_status(self.name, r.status_code, body, [self.api_key])

    async def _post_json(self, path: str, payload: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=TEST_TIMEOUT) as c:
                r = await c.post(self.base_url + path, json=payload, headers=self._headers())
                await self._check(r)
                return r.json()
        except LLMError:
            raise
        except Exception as e:  # noqa: BLE001 - mapped to a safe, typed error
            raise error_from_exception(self.name, self.base_url, e) from None

    async def _get_json(self, path: str) -> dict:
        async with httpx.AsyncClient(timeout=TEST_TIMEOUT) as c:
            r = await c.get(self.base_url + path, headers=self._headers())
            r.raise_for_status()
            return r.json()

    async def _timed(self, coro) -> TestResult:
        start = time.perf_counter()
        await coro
        return TestResult(ok=True, latency_ms=int((time.perf_counter() - start) * 1000))

    async def _stream_lines(self, path: str, payload: dict) -> AsyncIterator[str]:
        try:
            async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as c:
                async with c.stream(
                    "POST", self.base_url + path, json=payload, headers=self._headers()
                ) as r:
                    await self._check(r)
                    async for line in r.aiter_lines():
                        yield line
        except LLMError:
            raise
        except Exception as e:  # noqa: BLE001
            raise error_from_exception(self.name, self.base_url, e) from None
