"""Platform operator (hosted mode): sessions, audit log, tenant metadata, maintainer pings.

The operator sees counts and metadata only. Nothing here reads keys, prompts, profiles,
contacts or conversation text, and the /api/platform routes expose no such data (a test
enumerates them). Sessions use their own table and cookie, never a tenant admin's.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from mebot.models import (
    Admin,
    Bot,
    Message,
    PlatformAdmin,
    PlatformAudit,
    PlatformSession,
    UsageCounter,
    utcnow,
)

log = logging.getLogger("mebot.platform")

COOKIE = "mebot_platform"
TTL = timedelta(hours=12)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --- operator accounts / sessions --------------------------------------------------


def get_by_email(db: Session, email: str) -> PlatformAdmin | None:
    return db.scalar(
        select(PlatformAdmin).where(
            PlatformAdmin.email == email.strip().lower(), PlatformAdmin.deleted_at.is_(None)
        )
    )


def create_admin(db: Session, email: str, password_hash: str) -> PlatformAdmin:
    row = PlatformAdmin(email=email.strip().lower(), password_hash=password_hash)
    db.add(row)
    db.flush()
    return row


def create_session(db: Session, admin_id: str, now: datetime | None = None) -> str:
    now = now or utcnow()
    token = secrets.token_urlsafe(32)
    db.add(
        PlatformSession(
            id=_hash(token), platform_admin_id=admin_id, created_at=now, expires_at=now + TTL
        )
    )
    db.flush()
    return token


def resolve(db: Session, token: str | None, now: datetime | None = None) -> PlatformAdmin | None:
    if not token:
        return None
    s = db.get(PlatformSession, _hash(token))
    if s is None or s.expires_at <= (now or utcnow()):
        return None
    admin = db.get(PlatformAdmin, s.platform_admin_id)
    return admin if admin is not None and admin.deleted_at is None else None


def revoke(db: Session, token: str) -> None:
    db.execute(delete(PlatformSession).where(PlatformSession.id == _hash(token)))


# --- audit ---------------------------------------------------------------------------


def audit(db: Session, actor_id: str, action: str, bot_id: str | None = None, detail=None):
    db.add(
        PlatformAudit(
            actor_id=actor_id, action=action, target_bot_id=bot_id, detail=(detail or None)
        )
    )


def audit_page(db: Session, limit: int = 200) -> list[dict]:
    rows = db.execute(
        select(PlatformAudit, PlatformAdmin.email, Bot.slug)
        .outerjoin(PlatformAdmin, PlatformAdmin.id == PlatformAudit.actor_id)
        .outerjoin(Bot, Bot.id == PlatformAudit.target_bot_id)
        .order_by(PlatformAudit.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "at": a.created_at.isoformat(),
            "actor": email,
            "action": a.action,
            "tenant": slug,
            "detail": a.detail,
        }
        for a, email, slug in rows
    ]


# --- tenant metadata (counts only) -----------------------------------------------------


def _day(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def tenants(db: Session, now: datetime | None = None) -> list[dict]:
    """Every tenant with usage counts. Platform-wide aggregate: no content columns."""
    now = now or utcnow()
    d7, d30 = _day(now - timedelta(days=7)), _day(now - timedelta(days=30))

    def usage(since: str):
        return dict(
            db.execute(
                select(UsageCounter.bot_id, func.sum(UsageCounter.messages))
                .where(UsageCounter.scope == "bot_day", UsageCounter.window_start >= since)
                .group_by(UsageCounter.bot_id)
            ).all()
        )

    m7, m30 = usage(d7), usage(d30)
    tokens30 = dict(
        db.execute(
            select(UsageCounter.bot_id, func.sum(UsageCounter.tokens))
            .where(UsageCounter.scope == "bot_day", UsageCounter.window_start >= d30)
            .group_by(UsageCounter.bot_id)
        ).all()
    )
    last = dict(
        db.execute(
            select(Message.bot_id, func.max(Message.created_at)).group_by(Message.bot_id)
        ).all()
    )
    rows = db.execute(
        select(Bot, Admin.email, Admin.email_verified_at)
        .outerjoin(Admin, Admin.bot_id == Bot.id)
        .where(Bot.deleted_at.is_(None))
        .order_by(Bot.created_at.desc())
    ).all()
    out = []
    for bot, email, verified in rows:
        la = last.get(bot.id)
        out.append(
            {
                "id": bot.id,
                "slug": bot.slug,
                "owner_email": email,
                "email_verified": verified is not None,
                "created_at": bot.created_at.isoformat(),
                "status": bot.status,
                "status_reason": bot.status_reason,
                "plan": bot.plan,
                "setup_done": bot.setup_completed_at is not None,
                "messages_7d": int(m7.get(bot.id) or 0),
                "messages_30d": int(m30.get(bot.id) or 0),
                "tokens_30d": int(tokens30.get(bot.id) or 0),
                "last_active_at": la.isoformat() if isinstance(la, datetime) else la,
                "deletion_requested_at": bot.deletion_requested_at.isoformat()
                if bot.deletion_requested_at
                else None,
            }
        )
    return out


# --- maintainer pings ----------------------------------------------------------------


async def ping(settings, text: str) -> None:
    """Best-effort Telegram message to the maintainer; never raises, never blocks a caller
    for long (the client has its own timeout)."""
    token, chat = settings.platform_telegram_bot_token, settings.platform_telegram_chat_id
    if not (token and chat):
        return
    from mebot.telegram.client import TelegramClient

    try:
        await TelegramClient(token).send_message(chat, text)
    except Exception:  # noqa: BLE001 - a failed ping must not affect sign-up / suspension
        log.warning("maintainer ping failed")
