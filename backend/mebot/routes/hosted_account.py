"""Hosted mode, the logged-in owner's own account: status, per-tenant setup, slug change,
data export and deletion. Everything acts on the session's bot only (OWNER_PATHS)."""

import io
import json
import zipfile
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from mebot.auth import passwords
from mebot.auth.cookies import clear_session_cookie
from mebot.config import Settings
from mebot.db import get_db
from mebot.deps import (
    CurrentAdmin,
    csrf_on_mutation,
    get_current_admin,
    get_current_bot,
    get_settings,
)
from mebot.errors import ApiError
from mebot.hosted.slugs import slug_error
from mebot.llm import service as llm
from mebot.models import Base, Bot, SlugRedirect, utcnow
from mebot.profile.schemas import IdentityIn
from mebot.repos import admin_sessions, bots, logs
from mebot.repos import profile_items as profile
from mebot.routes.hosted_accounts import require_hosted

router = APIRouter(
    prefix="/api/hosted/account",
    dependencies=[
        Depends(require_hosted),
        Depends(get_current_admin),
        Depends(csrf_on_mutation),
    ],
)

REDIRECT_DAYS = 30
PURGE_AFTER = timedelta(days=7)
# What the owner gets in the export: their content, never secrets or operational state.
EXPORT_TABLES = (
    "profile_identity", "profile_notes", "profile_links", "experiences", "educations",
    "skills", "projects", "interests", "faqs", "avoid_topics", "learned_facts",
    "open_questions", "sessions", "messages", "contacts", "widget_settings", "bot_limits",
)  # fmt: skip


class SetupReq(BaseModel):
    bot_name: str = Field(max_length=80)
    full_name: str | None = Field(default=None, max_length=200)
    headline: str | None = Field(default=None, max_length=200)
    llm: llm.LLMInput

    @field_validator("bot_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v


class SlugReq(BaseModel):
    slug: str = Field(max_length=40)

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = v.strip().lower()
        err = slug_error(v)
        if err:
            raise ValueError(err)
        return v


class DeleteReq(BaseModel):
    password: str = Field(max_length=passwords.MAX_LENGTH)


def _view(db: Session, bot: Bot, current: CurrentAdmin, settings: Settings) -> dict:
    live = bots.get_live_by_slug_id(db, bot.id) is not None
    return {
        "email": current.admin.email,
        "email_verified": current.admin.email_verified_at is not None,
        "bot_name": bot.name,
        "slug": bot.slug,
        "public_key": bot.public_key,
        "plan": bot.plan,
        "setup_done": bot.setup_completed_at is not None,
        "live": live,
        "public_path": f"/b/{bot.slug}",
        "hosted_domain": settings.hosted_domain,
    }


@router.get("")
def account(
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    current: CurrentAdmin = Depends(get_current_admin),
):
    return _view(db, bot, current, request.app.state.settings)


@router.post("/setup")
async def setup(
    req: SetupReq,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    current: CurrentAdmin = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
):
    """The per-tenant wizard's last step: name, tested AI provider, profile basics."""
    if bot.setup_completed_at is not None:
        raise ApiError(409, "SETUP_COMPLETED", "Your assistant is already set up.")
    llm.validate(req.llm, prefix="llm.")
    cfg = llm.resolve_input(req.llm, settings)
    await llm.run_test(cfg)  # 422 LLM_TEST_FAILED; nothing saved yet
    bot.name = req.bot_name
    llm.store(db, bot.id, cfg, request.app.state.secret_key)
    if profile.get_identity(db, bot.id) is None:
        profile.put_identity(
            db,
            bot.id,
            IdentityIn(full_name=req.full_name or req.bot_name, headline=req.headline or ""),
        )
    bot.setup_completed_at = utcnow()
    bot.updated_at = utcnow()
    db.commit()
    return _view(db, bot, current, settings)


@router.put("/slug")
def change_slug(
    req: SlugReq,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    current: CurrentAdmin = Depends(get_current_admin),
):
    old = bot.slug
    if req.slug == old:
        return _view(db, bot, current, request.app.state.settings)
    own = db.scalar(
        select(SlugRedirect).where(SlugRedirect.old_slug == req.slug, SlugRedirect.bot_id == bot.id)
    )
    if own is not None:  # taking back one of our own old slugs
        db.delete(own)
        db.flush()
    elif bots.slug_taken(db, req.slug):
        raise ApiError(409, "SLUG_TAKEN", "That address is taken. Pick another.")
    now = utcnow()
    db.add(
        SlugRedirect(old_slug=old, bot_id=bot.id, expires_at=now + timedelta(days=REDIRECT_DAYS))
    )
    bot.slug = req.slug
    bot.updated_at = now
    logs.add(db, bot.id, None, "slug_changed")
    db.commit()
    return _view(db, bot, current, request.app.state.settings)


def _jsonable(v):
    return v.astimezone(UTC).isoformat() if isinstance(v, datetime) else v


def export_rows(db: Session, bot_id: str) -> dict[str, list[dict]]:
    out = {}
    for name in EXPORT_TABLES:
        table = Base.metadata.tables[name]
        rows = db.execute(select(table).where(table.c.bot_id == bot_id)).mappings()
        out[name] = [{k: _jsonable(v) for k, v in r.items()} for r in rows]
    return out


@router.get("/export")
def export(db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    data = export_rows(db, bot.id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "README.txt",
            f"mebot export of '{bot.slug}', {utcnow().isoformat()}. One JSON file per table.",
        )
        for name, rows in data.items():
            z.writestr(f"{name}.json", json.dumps(rows, ensure_ascii=False, indent=1))
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="mebot-{bot.slug}.zip"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/delete", status_code=204)
async def delete_account(
    req: DeleteReq,
    response: Response,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    current: CurrentAdmin = Depends(get_current_admin),
):
    """Soft delete: offline at once, hard purge after PURGE_AFTER (hosted.purge)."""
    ok = await run_in_threadpool(
        passwords.verify_password, current.admin.password_hash, req.password
    )
    if not ok:
        raise ApiError(400, "INVALID_PASSWORD", "Password is incorrect")
    now = utcnow()
    bot.status = "deleted"
    bot.deletion_requested_at = now
    bot.updated_at = now
    current.admin.deleted_at = now
    admin_sessions.revoke_for_bot(db, bot.id)
    admin_sessions.revoke_all(db, current.admin.id)  # commits
    clear_session_cookie(response)
