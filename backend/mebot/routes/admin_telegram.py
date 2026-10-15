"""Owner-only Telegram settings. The bot token goes in, never out (only last4)."""

import re
import secrets
from datetime import UTC
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from mebot.db import get_db
from mebot.deps import csrf_on_mutation, get_current_admin, get_current_bot, require_setup_done
from mebot.errors import ApiError
from mebot.models import Bot, TelegramConfig
from mebot.repos import logs
from mebot.telegram import outbox, repo
from mebot.telegram.client import TelegramClient, TelegramError

router = APIRouter(
    prefix="/api/admin/telegram",
    dependencies=[
        Depends(require_setup_done),
        Depends(get_current_admin),
        Depends(csrf_on_mutation),
    ],
)

TOKEN_RE = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{20,80}$")
TOGGLES = (
    "notify_new_session",
    "notify_every_question",
    "notify_unanswered",
    "notify_contact",
    "notify_limits",
    "daily_digest",
)


class TokenIn(BaseModel):
    bot_token: str = Field(max_length=200)

    @field_validator("bot_token")
    @classmethod
    def _shape(cls, v: str) -> str:
        v = v.strip()
        if not TOKEN_RE.match(v):
            raise ValueError("doesn't look like a BotFather token (123456:ABC…)")
        return v


def _iso(dt) -> str | None:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def view(row: TelegramConfig | None, request: Request, db: Session) -> dict:
    configured = bool(row and row.bot_token_encrypted)
    body = {
        "configured": configured,
        "linked": bool(configured and row.chat_id),
        "bot_username": row.bot_username if configured else None,
        "bot_token_last4": row.bot_token_last4 if configured else None,
        "mode": row.mode if row else "polling",
        "webhook_available": bool(request.app.state.settings.public_url),
        "error": row.error if row else None,
        "digest_hour": row.digest_hour if row else 21,
        "timezone": row.timezone if row else "UTC",
        "outbox": _outbox(db, row),
    }
    for t in TOGGLES:
        body[t] = getattr(row, t) if row else TelegramConfig.__table__.c[t].default.arg
    return body


def _outbox(db: Session, row: TelegramConfig | None) -> dict:
    if row is None:
        return {"pending": 0, "failed": 0, "dead": 0, "last_sent_at": None}
    s = outbox.stats(db, row.bot_id)
    return {**s, "last_sent_at": _iso(s["last_sent_at"])}


class SettingsIn(BaseModel):
    """Partial update of toggles, digest time, timezone and receive mode."""

    model_config = ConfigDict(extra="forbid")

    notify_new_session: bool = None
    notify_every_question: bool = None
    notify_unanswered: bool = None
    notify_contact: bool = None
    notify_limits: bool = None
    daily_digest: bool = None
    digest_hour: int = Field(default=None, ge=0, le=23)
    timezone: str = Field(default=None, max_length=64)
    mode: Literal["polling", "webhook"] = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("unknown IANA timezone (e.g. Europe/Berlin)") from None
        return v


def _service_changed(request: Request) -> None:
    svc = getattr(request.app.state, "telegram", None)
    if svc is not None:
        svc.reconcile()


def _linked_client(row: TelegramConfig | None, request: Request) -> TelegramClient:
    client = repo.client_for(row, request.app.state.secret_key)
    if client is None or not row.chat_id:
        raise ApiError(409, "TELEGRAM_NOT_LINKED", "Connect and link Telegram first.")
    return client


@router.get("")
def get_telegram(
    request: Request, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)
):
    return view(repo.get(db, bot.id), request, db)


@router.put("")
async def put_token(
    req: TokenIn,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    try:
        me = await TelegramClient(req.bot_token).get_me()
    except TelegramError as e:
        if e.kind == "auth":
            raise ApiError(
                422,
                "TELEGRAM_TOKEN_INVALID",
                "Telegram rejected this token. Copy it again from @BotFather.",
                [{"field": "bot_token", "message": "rejected by Telegram"}],
            ) from None
        raise ApiError(
            422, "TELEGRAM_UNREACHABLE", "Could not reach Telegram. Try again in a minute."
        ) from None
    username = str((me or {}).get("username") or "")
    if not username:
        raise ApiError(422, "TELEGRAM_TOKEN_INVALID", "That token isn't for a bot.")
    row = repo.save_token(db, bot.id, request.app.state.secret_key, req.bot_token, username)
    logs.add(db, bot.id, None, "telegram_token_saved", detail=f"@{username}")
    db.commit()
    _service_changed(request)
    return view(row, request, db)


@router.patch("")
async def patch_settings(
    req: SettingsIn,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    row = repo.get(db, bot.id)
    client = repo.client_for(row, request.app.state.secret_key)
    if client is None:
        raise ApiError(409, "TELEGRAM_NOT_CONFIGURED", "Save your bot token first.")
    values = req.model_dump(exclude_unset=True)
    mode = values.pop("mode", None)
    for k, v in values.items():
        setattr(row, k, v)
    if mode and mode != row.mode:
        await _switch_mode(row, mode, client, request, bot.id)
    db.commit()
    _service_changed(request)
    return view(row, request, db)


async def _switch_mode(row: TelegramConfig, mode: str, client, request: Request, bot_id: str):
    public_url = request.app.state.settings.public_url
    try:
        if mode == "webhook":
            if not public_url:
                raise ApiError(
                    422,
                    "VALIDATION_ERROR",
                    "Invalid request",
                    [{"field": "mode", "message": "set PUBLIC_URL to use a webhook"}],
                )
            secret = secrets.token_urlsafe(32)
            url = f"{public_url.rstrip('/')}/api/telegram/webhook/{bot_id}"
            await client.set_webhook(url, secret)
            row.webhook_secret = secret
        else:
            await client.delete_webhook()
            row.webhook_secret = None
    except TelegramError as e:
        raise ApiError(502, "TELEGRAM_ERROR", e.message) from None
    row.mode = mode
    row.lease_owner = None
    row.lease_expires_at = None


@router.post("/link")
def create_link(
    request: Request, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)
):
    row = repo.get(db, bot.id)
    if row is None or not row.bot_token_encrypted or not row.bot_username:
        raise ApiError(409, "TELEGRAM_NOT_CONFIGURED", "Save your bot token first.")
    code, expires = repo.new_link_code(db, row)
    db.commit()
    return {
        "deep_link": f"https://t.me/{row.bot_username}?start={code}",
        "expires_at": _iso(expires),
    }


@router.post("/test", status_code=204)
async def send_test(
    request: Request, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)
):
    row = repo.get(db, bot.id)
    client = _linked_client(row, request)
    try:
        await client.send_message(row.chat_id, "✅ Test message from mebot. Notifications work.")
    except TelegramError as e:
        raise ApiError(502, "TELEGRAM_ERROR", e.message) from None
    return Response(status_code=204)


@router.delete("", status_code=204)
async def unlink(
    request: Request, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)
):
    row = repo.get(db, bot.id)
    if row is not None:
        client = repo.client_for(row, request.app.state.secret_key)
        if client is not None and row.mode == "webhook":
            try:
                await client.delete_webhook()
            except TelegramError:
                pass  # best effort: the token is forgotten either way
        repo.forget(db, row)
        logs.add(db, bot.id, None, "telegram_unlinked")
        db.commit()
    _service_changed(request)
    return Response(status_code=204)
