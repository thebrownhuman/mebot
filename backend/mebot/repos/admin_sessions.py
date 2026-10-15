"""Admin login sessions. Only sha256(token) is stored; the raw token lives in the cookie."""

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from mebot.models import AdminSession, utcnow

TTL = timedelta(days=14)
REFRESH_BELOW = timedelta(days=7)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create(
    db: Session,
    admin_id: str,
    ip: str | None = None,
    user_agent: str | None = None,
    now: datetime | None = None,
) -> str:
    now = now or utcnow()
    token = secrets.token_urlsafe(32)
    db.add(
        AdminSession(
            id=hash_token(token),
            admin_id=admin_id,
            created_at=now,
            expires_at=now + TTL,
            last_seen_at=now,
            ip=ip,
            user_agent=(user_agent or "")[:512] or None,
        )
    )
    db.flush()
    return token


def resolve(db: Session, token: str, now: datetime | None = None) -> AdminSession | None:
    """Return the live session for token (sliding its expiry), or None. Commits."""
    if not token:
        return None
    now = now or utcnow()
    s = db.get(AdminSession, hash_token(token))
    if s is None:
        return None
    if s.expires_at <= now:
        db.delete(s)
        db.commit()
        return None
    s.last_seen_at = now
    if s.expires_at - now < REFRESH_BELOW:
        s.expires_at = now + TTL
    db.commit()
    return s


def revoke(db: Session, token: str) -> None:
    db.execute(delete(AdminSession).where(AdminSession.id == hash_token(token)))
    db.commit()


def revoke_all(db: Session, admin_id: str, except_token: str | None = None) -> None:
    stmt = delete(AdminSession).where(AdminSession.admin_id == admin_id)
    if except_token:
        stmt = stmt.where(AdminSession.id != hash_token(except_token))
    db.execute(stmt)
    db.commit()


def purge_expired(db: Session, now: datetime | None = None) -> int:
    result = db.execute(delete(AdminSession).where(AdminSession.expires_at <= (now or utcnow())))
    db.commit()
    return result.rowcount
