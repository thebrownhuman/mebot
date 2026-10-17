"""Single-use account tokens (e-mail verification, password reset). Platform tables:
keyed by admin, not bot. Only sha256(token) is stored; the raw token goes in the mail."""

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from mebot.models import EmailVerification, PasswordReset, utcnow

VERIFY_TTL = timedelta(hours=24)
RESET_TTL = timedelta(minutes=30)
KINDS = {"verify": (EmailVerification, VERIFY_TTL), "reset": (PasswordReset, RESET_TTL)}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue(db: Session, kind: str, admin_id: str, now: datetime | None = None) -> str:
    """New token; earlier unused tokens of the same kind for this admin stop working."""
    model, ttl = KINDS[kind]
    now = now or utcnow()
    db.execute(delete(model).where(model.admin_id == admin_id, model.used_at.is_(None)))
    token = secrets.token_urlsafe(32)
    db.add(model(id=_hash(token), admin_id=admin_id, created_at=now, expires_at=now + ttl))
    db.flush()
    return token


def consume(db: Session, kind: str, token: str, now: datetime | None = None) -> str | None:
    """Admin id if token is valid, unused and unexpired; marks it used (atomically)."""
    model, _ = KINDS[kind]
    now = now or utcnow()
    tid = _hash(token or "")
    row = db.get(model, tid)
    if row is None or row.used_at is not None or row.expires_at <= now:
        return None
    result = db.execute(
        update(model)
        .where(model.id == tid, model.used_at.is_(None))
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    return row.admin_id if result.rowcount == 1 else None


def purge(db: Session, now: datetime | None = None) -> None:
    cutoff = (now or utcnow()) - timedelta(days=7)
    for model, _ in KINDS.values():
        db.execute(delete(model).where(model.expires_at <= cutoff))
