"""Registry client: signed requests to ONE host, with hard limits on what comes back.

It only ever talks to ``REGISTRY_URL``: redirects are not followed (so a compromised or
misconfigured registry can't bounce us elsewhere), calls time out after 5 s, responses are
capped at 64 KB, and ``/v1/latest`` is schema-validated before anything is used.
"""

import asyncio
import json
import re
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from mebot.telemetry import identity, semver

TIMEOUT_SECONDS = 5.0
TOTAL_SECONDS = 10.0
MAX_RESPONSE_BYTES = 64 * 1024
_VERSION_FIELD = Field(max_length=40)


class RegistryError(Exception):
    """kind: network | http | redirect | too_large | schema."""

    def __init__(self, kind: str, message: str = "", status: int | None = None):
        super().__init__(f"{kind}: {message}" if message else kind)
        self.kind, self.status = kind, status


def _http_url(v: str | None) -> str | None:
    """Only http(s) links are ever shown or followed from registry data."""
    if v and re.match(r"^https?://[^\s]+$", v):
        return v
    return None


class Advisory(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(max_length=64)
    severity: str = Field(default="medium", max_length=16)
    affected: str = Field(max_length=64)
    title: str = Field(max_length=200)
    url: str | None = Field(default=None, max_length=300)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return _http_url(v)


class Latest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    latest: str = _VERSION_FIELD
    min_supported: str | None = Field(default=None, max_length=40)
    released_at: str | None = Field(default=None, max_length=40)
    notes_url: str | None = Field(default=None, max_length=300)
    advisories: list[Advisory] = Field(default_factory=list, max_length=50)

    @field_validator("latest")
    @classmethod
    def _latest(cls, v: str) -> str:
        if not semver.valid(v):
            raise ValueError("latest is not a version")
        return v

    @field_validator("min_supported")
    @classmethod
    def _min(cls, v: str | None) -> str | None:
        return v if semver.valid(v) else None

    @field_validator("notes_url")
    @classmethod
    def _notes(cls, v: str | None) -> str | None:
        return _http_url(v)


class RegistryClient:
    def __init__(
        self,
        base_url: str,
        key: identity.InstallKey,
        version: str,
        mode: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.host = urlsplit(self.base_url).netloc
        self.key, self.version, self.mode = key, version, mode
        self._transport = transport

    # --- payloads (also what the Account page shows as "what's sent") -------------------

    def heartbeat_payload(self) -> dict:
        return {
            "install_id": self.key.install_id,
            "public_key": self.key.public_b64,
            "version": self.version,
            "mode": self.mode,
        }

    def register_payload(self, email: str, site_url: str) -> dict:
        return {
            "install_id": self.key.install_id,
            "public_key": self.key.public_b64,
            "version": self.version,
            "email": email,
            "site_url": site_url,
        }

    # --- calls --------------------------------------------------------------------------

    async def heartbeat(self, now_ts: int) -> dict:
        payload = self.heartbeat_payload()
        await self._call("POST", "/v1/heartbeat", now_ts, payload)
        return payload

    async def register(self, email: str, site_url: str, now_ts: int) -> dict:
        payload = self.register_payload(email, site_url)
        await self._call("POST", "/v1/register", now_ts, payload)
        return payload

    async def unregister(self, now_ts: int) -> None:
        await self._call("DELETE", "/v1/register", now_ts, None)

    async def latest(self) -> Latest:
        raw = await self._call("GET", "/v1/latest", None, None)
        try:
            return Latest.model_validate(json.loads(raw))
        except (ValueError, ValidationError):
            raise RegistryError("schema", "unexpected /v1/latest response") from None

    async def _call(
        self, method: str, path: str, now_ts: int | None, payload: dict | None
    ) -> bytes:
        url = f"{self.base_url}{path}"
        if urlsplit(url).netloc != self.host:  # belt and braces: paths are constants
            raise RegistryError("redirect", "refusing to leave the registry host")
        body = b""
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        if now_ts is not None:  # latest is public; everything else is signed
            headers.update(identity.signed_headers(self.key, method, path, body, now_ts))
        try:
            # The per-read timeout doesn't stop a server that trickles bytes forever.
            async with (
                asyncio.timeout(TOTAL_SECONDS),
                httpx.AsyncClient(
                    transport=self._transport, follow_redirects=False, timeout=TIMEOUT_SECONDS
                ) as client,
            ):
                async with client.stream(method, url, content=body or None, headers=headers) as r:
                    if 300 <= r.status_code < 400:
                        raise RegistryError("redirect", f"HTTP {r.status_code}", r.status_code)
                    data = bytearray()
                    async for chunk in r.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_RESPONSE_BYTES:
                            raise RegistryError("too_large", "response over 64 KB")
                    if r.status_code >= 400:
                        raise RegistryError("http", _error_code(bytes(data)), r.status_code)
                    return bytes(data)
        except httpx.HTTPError as e:
            raise RegistryError("network", type(e).__name__) from None
        except TimeoutError:
            raise RegistryError("network", "Timeout") from None


def _error_code(raw: bytes) -> str:
    try:
        return str(json.loads(raw)["error"]["code"])[:60]
    except (ValueError, KeyError, TypeError):
        return "error"
