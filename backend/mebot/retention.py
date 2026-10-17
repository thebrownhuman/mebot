"""Conversation retention: HARD deletes (personal-data removal, a documented exception to
soft delete). Messages, session-linked access_log rows and contacts go together with their
session. ``usage_counters`` and the Telegram outbox keep their own purge rules."""

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from mebot.models import AccessLog, Bot, ChatSession, Contact, Message, utcnow
from mebot.repos import logs

_CHUNK = 500


def _chunks(ids: list[str]):
    for i in range(0, len(ids), _CHUNK):
        yield ids[i : i + _CHUNK]


def delete_sessions(db: Session, bot_id: str, sids: list[str]) -> dict[str, int]:
    """Hard-delete sessions with their messages, contacts and session-linked log rows."""
    out = {"sessions": 0, "messages": 0, "contacts": 0}
    for part in _chunks(sids):
        out["messages"] += db.execute(
            delete(Message).where(Message.bot_id == bot_id, Message.session_id.in_(part))
        ).rowcount
        out["contacts"] += db.execute(
            delete(Contact).where(Contact.bot_id == bot_id, Contact.session_id.in_(part))
        ).rowcount
        db.execute(
            delete(AccessLog).where(AccessLog.bot_id == bot_id, AccessLog.session_id.in_(part))
        )
        out["sessions"] += db.execute(
            delete(ChatSession).where(ChatSession.bot_id == bot_id, ChatSession.id.in_(part))
        ).rowcount
    return out


def purge_bot(db: Session, bot_id: str, days: int, now: datetime | None = None) -> dict[str, int]:
    """Delete everything older than ``days``; log counts only. Caller commits."""
    cutoff = (now or utcnow()) - timedelta(days=days)
    sids = list(
        db.scalars(
            select(ChatSession.id).where(
                ChatSession.bot_id == bot_id, ChatSession.started_at < cutoff
            )
        )
    )
    out = delete_sessions(db, bot_id, sids)
    # Stragglers: old messages in a still-young session, and old sessionless contacts.
    out["messages"] += db.execute(
        delete(Message).where(Message.bot_id == bot_id, Message.created_at < cutoff)
    ).rowcount
    out["contacts"] += db.execute(
        delete(Contact).where(Contact.bot_id == bot_id, Contact.created_at < cutoff)
    ).rowcount
    if any(out.values()):
        logs.add(db, bot_id, None, "RETENTION_PURGED", detail=_counts(out))
    return out


def _counts(out: dict[str, int]) -> str:
    return f"sessions={out['sessions']} messages={out['messages']} contacts={out['contacts']}"


def purge_all_bots(factory: sessionmaker, now: datetime | None = None) -> int:
    """Daily job: apply every bot's window. Returns the number of sessions deleted."""
    total = 0
    with factory() as db:
        rows = db.execute(
            select(Bot.id, Bot.retention_days).where(
                Bot.retention_days.is_not(None), Bot.deleted_at.is_(None)
            )
        ).all()
        for bot_id, days in rows:
            total += purge_bot(db, bot_id, days, now)["sessions"]
        db.commit()
    return total


def preview(db: Session, bot_id: str, days: int | None, now: datetime | None = None) -> int:
    """How many conversations a window of ``days`` would delete right now."""
    if days is None:
        return 0
    cutoff = (now or utcnow()) - timedelta(days=days)
    return (
        db.scalar(
            select(func.count())
            .select_from(ChatSession)
            .where(ChatSession.bot_id == bot_id, ChatSession.started_at < cutoff)
        )
        or 0
    )


def delete_all(db: Session, bot_id: str) -> int:
    """Owner-initiated: remove every conversation. Returns sessions deleted. Caller commits."""
    sids = list(db.scalars(select(ChatSession.id).where(ChatSession.bot_id == bot_id)))
    out = delete_sessions(db, bot_id, sids)
    out["messages"] += db.execute(delete(Message).where(Message.bot_id == bot_id)).rowcount
    out["contacts"] += db.execute(delete(Contact).where(Contact.bot_id == bot_id)).rowcount
    if any(out.values()):
        logs.add(db, bot_id, None, "CONVERSATIONS_DELETED", detail=_counts(out))
    return out["sessions"]
