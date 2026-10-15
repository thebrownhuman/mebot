"""Glue between API input, stored config and provider clients.

Clients are always created through ``factory.build_client`` (looked up at call time so
tests can swap it). The plaintext key only ever lives in memory for the duration of a
call; responses and logs get provider/model/last4 at most.
"""

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from mebot.config import Settings
from mebot.crypto import decrypt_secret, encrypt_secret
from mebot.errors import ApiError
from mebot.llm import factory
from mebot.llm.base import LLMClient, LLMError, TestResult
from mebot.llm.providers import Provider, get_provider
from mebot.models import LLMConfig
from mebot.repos import llm_configs


class LLMInput(BaseModel):
    provider: str = Field(max_length=40)
    model: str = Field(max_length=200)
    api_key: str | None = Field(default=None, max_length=1000)
    base_url: str | None = Field(default=None, max_length=500)

    @field_validator("model", "api_key", "base_url")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


@dataclass
class ResolvedLLM:
    """A complete, usable config (key decrypted)."""

    provider: str
    model: str
    base_url: str | None
    api_key: str | None
    temperature: float = llm_configs.DEFAULT_TEMPERATURE
    max_tokens: int = llm_configs.DEFAULT_MAX_TOKENS

    def client(self) -> LLMClient:
        return factory.build_client(self.provider, api_key=self.api_key, base_url=self.base_url)


ConfigStatus = Literal["ok", "missing", "undecryptable"]


def _invalid(prefix: str, field: str, message: str) -> ApiError:
    name = f"{prefix}{field}"
    return ApiError(422, "VALIDATION_ERROR", message, details=[{"field": name, "message": message}])


def validate(inp: LLMInput, prefix: str = "", key_optional: bool = False) -> Provider:
    """Check provider/model/key/base_url. key_optional: caller supplies a saved key."""
    provider = get_provider(inp.provider)
    if provider is None:
        raise _invalid(prefix, "provider", "Unknown provider.")
    if not inp.model:
        raise _invalid(prefix, "model", "Choose a model.")
    if provider.key_required and not inp.api_key and not key_optional:
        raise _invalid(prefix, "api_key", f"{provider.name} needs your API key.")
    if inp.base_url:
        parts = urlsplit(inp.base_url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise _invalid(prefix, "base_url", "Base URL must be an http(s) URL.")
    elif provider.base_url_required:
        raise _invalid(prefix, "base_url", "Enter the base URL of your OpenAI-compatible API.")
    return provider


def resolve_input(inp: LLMInput, settings: Settings, api_key: str | None = None) -> ResolvedLLM:
    base_url = inp.base_url
    if base_url is None and inp.provider == "ollama":
        base_url = settings.ollama_host
    return ResolvedLLM(
        provider=inp.provider,
        model=inp.model,
        base_url=base_url,
        api_key=inp.api_key or api_key,
    )


def failed(err: LLMError) -> ApiError:
    return ApiError(422, "LLM_TEST_FAILED", err.message)


async def run_test(cfg: ResolvedLLM) -> TestResult:
    """Tiny live call; raises ApiError(422, LLM_TEST_FAILED) with a scrubbed message."""
    try:
        return await cfg.client().test(model=cfg.model)
    except LLMError as e:
        raise failed(e) from None


async def list_models(cfg: ResolvedLLM) -> list[str]:
    try:
        return await cfg.client().list_models()
    except Exception:  # noqa: BLE001 - best effort
        return []


def encrypt_key(secret_key: str, api_key: str | None) -> tuple[str | None, str | None]:
    if not api_key:
        return None, None
    return encrypt_secret(secret_key, api_key), api_key[-4:]


def store(db: Session, bot_id: str, cfg: ResolvedLLM, secret_key: str) -> LLMConfig:
    enc, last4 = encrypt_key(secret_key, cfg.api_key)
    return llm_configs.save(
        db,
        bot_id,
        provider=cfg.provider,
        model=cfg.model,
        base_url=cfg.base_url,
        api_key_encrypted=enc,
        api_key_last4=last4,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
    )


def load(
    db: Session, bot_id: str, secret_key: str
) -> tuple[ConfigStatus, LLMConfig | None, ResolvedLLM | None]:
    row = llm_configs.get(db, bot_id)
    if row is None or get_provider(row.provider) is None:
        return "missing", row, None
    api_key = None
    if row.api_key_encrypted:
        api_key = decrypt_secret(secret_key, row.api_key_encrypted)
        if api_key is None:
            return "undecryptable", row, None
    return (
        "ok",
        row,
        ResolvedLLM(
            provider=row.provider,
            model=row.model,
            base_url=row.base_url,
            api_key=api_key,
            temperature=row.temperature,
            max_tokens=row.max_tokens,
        ),
    )
