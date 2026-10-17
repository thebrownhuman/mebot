"""Invite codes for SIGNUP_MODE=invite. Platform table; only sha256(code) is stored."""

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from mebot.models import Invite, utcnow


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().encode()).hexdigest()


def create(db: Session, note: str | None = None, days: int | None = 30) -> str:
    code = secrets.token_urlsafe(12)
    expires = utcnow() + timedelta(days=days) if days else None
    db.add(Invite(code_hash=_hash(code), note=note, expires_at=expires))
    db.flush()
    return code


def _usable(now):
    return (
        Invite.used_at.is_(None),
        Invite.deleted_at.is_(None),
        (Invite.expires_at.is_(None)) | (Invite.expires_at > now),
    )


def valid(db: Session, code: str, now: datetime | None = None) -> bool:
    now = now or utcnow()
    q = select(Invite.id).where(Invite.code_hash == _hash(code or ""), *_usable(now))
    return db.scalar(q) is not None


def consume(db: Session, code: str, admin_id: str, now: datetime | None = None) -> bool:
    now = now or utcnow()
    result = db.execute(
        update(Invite)
        .where(Invite.code_hash == _hash(code or ""), *_usable(now))
        .values(used_at=now, used_by_admin_id=admin_id)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1
