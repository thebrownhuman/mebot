"""Owner-only LLM settings. The API key goes in, never out (only has_key + last4)."""

from fastapi import APIRouter, Body, Depends, Query, Request
from pydantic import Field
from sqlalchemy.orm import Session

from mebot.config import Settings
from mebot.db import get_db
from mebot.deps import (
    csrf_on_mutation,
    get_current_admin,
    get_current_bot,
    get_settings,
    require_setup_done,
)
from mebot.errors import ApiError
from mebot.llm import service as llm
from mebot.llm.providers import PROVIDERS, get_provider
from mebot.models import Bot, LLMConfig
from mebot.repos import llm_configs

router = APIRouter(
    prefix="/api/admin/llm",
    dependencies=[
        Depends(require_setup_done),
        Depends(get_current_admin),
        Depends(csrf_on_mutation),
    ],
)


class AdminLLMReq(llm.LLMInput):
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=8192)


def _view(status: llm.ConfigStatus, row: LLMConfig | None) -> dict:
    return {
        "configured": status == "ok",
        "status": status,
        "provider": row.provider if row else None,
        "model": row.model if row else None,
        "base_url": row.base_url if row else None,
        "has_key": bool(row and row.api_key_encrypted and status == "ok"),
        "api_key_last4": row.api_key_last4 if row and status == "ok" else None,
        "temperature": row.temperature if row else llm_configs.DEFAULT_TEMPERATURE,
        "max_tokens": row.max_tokens if row else llm_configs.DEFAULT_MAX_TOKENS,
        "last_tested_at": row.last_tested_at.isoformat() if row and row.last_tested_at else None,
        "last_test_ok": row.last_test_ok if row else None,
    }


def _resolve(
    req: AdminLLMReq, request: Request, db: Session, bot: Bot, settings: Settings
) -> tuple[llm.ResolvedLLM, LLMConfig | None]:
    """Build a config from the request, reusing the saved key only for the same provider."""
    llm.validate(req, key_optional=True)
    status, row, current = llm.load(db, bot.id, request.app.state.secret_key)
    saved_key = None
    if current and row and row.provider == req.provider:
        saved_key = current.api_key
    provider = get_provider(req.provider)
    if provider.key_required and not (req.api_key or saved_key):
        msg = (
            f"Enter your {provider.name} API key."
            if status != "undecryptable"
            else "The saved key can no longer be decrypted (SECRET_KEY changed). Enter it again."
        )
        raise ApiError(422, "VALIDATION_ERROR", msg, details=[{"field": "api_key", "message": msg}])
    cfg = llm.resolve_input(req, settings, api_key=saved_key)
    cfg.temperature = (
        req.temperature
        if req.temperature is not None
        else (row.temperature if row else llm_configs.DEFAULT_TEMPERATURE)
    )
    cfg.max_tokens = (
        req.max_tokens
        if req.max_tokens is not None
        else (row.max_tokens if row else llm_configs.DEFAULT_MAX_TOKENS)
    )
    return cfg, row


@router.get("")
def read(request: Request, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    status, row, _ = llm.load(db, bot.id, request.app.state.secret_key)
    return _view(status, row)


@router.put("")
async def update(
    req: AdminLLMReq,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    settings: Settings = Depends(get_settings),
):
    cfg, _ = _resolve(req, request, db, bot, settings)
    await llm.run_test(cfg)  # 422 on failure; saved config untouched
    row = llm.store(db, bot.id, cfg, request.app.state.secret_key)
    db.commit()
    return _view("ok", row)


@router.post("/test")
async def test(
    request: Request,
    req: AdminLLMReq | None = Body(default=None),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    settings: Settings = Depends(get_settings),
):
    if req is not None:
        cfg, _ = _resolve(req, request, db, bot, settings)
        result = await llm.run_test(cfg)
        return {"ok": result.ok, "latency_ms": result.latency_ms}

    status, row, cfg = llm.load(db, bot.id, request.app.state.secret_key)
    if cfg is None:
        raise ApiError(422, "LLM_NOT_CONFIGURED", "No working AI provider is saved yet.")
    try:
        result = await llm.run_test(cfg)
    except ApiError:
        llm_configs.record_test(db, row, ok=False)
        db.commit()
        raise
    llm_configs.record_test(db, row, ok=True)
    db.commit()
    return {"ok": result.ok, "latency_ms": result.latency_ms}


@router.get("/models")
async def models(
    request: Request,
    provider: str = Query(max_length=40),
    base_url: str | None = Query(default=None, max_length=500),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    settings: Settings = Depends(get_settings),
):
    """Model list using the saved key (only when the provider matches the saved one)."""
    if get_provider(provider) is None:
        raise ApiError(422, "VALIDATION_ERROR", "Unknown provider.")
    _, row, current = llm.load(db, bot.id, request.app.state.secret_key)
    key = current.api_key if current and row and row.provider == provider else None
    if base_url is None and current and row and row.provider == provider:
        base_url = current.base_url
    inp = llm.LLMInput(provider=provider, model="-", base_url=base_url)
    return {"models": await llm.list_models(llm.resolve_input(inp, settings, api_key=key))}


@router.post("/models")
async def models_with_key(
    req: AdminLLMReq,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    settings: Settings = Depends(get_settings),
):
    """Model list for an unsaved key (POST so the key never sits in a URL)."""
    if get_provider(req.provider) is None:
        raise ApiError(422, "VALIDATION_ERROR", "Unknown provider.")
    _, row, current = llm.load(db, bot.id, request.app.state.secret_key)
    key = current.api_key if current and row and row.provider == req.provider else None
    return {"models": await llm.list_models(llm.resolve_input(req, settings, api_key=key))}


@router.get("/providers")
def providers():
    return {"providers": [p.public() for p in PROVIDERS]}
