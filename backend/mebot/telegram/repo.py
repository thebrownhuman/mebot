"""telegram_configs access: token storage, link codes, lease."""

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from mebot.crypto import TELEGRAM_INFO, decrypt_secret, encrypt_secret
from mebot.models import TelegramConfig, utcnow
from mebot.telegram.client import TelegramClient

LINK_TTL = timedelta(minutes=10)
CODE_LEN = 16


def get(db: Session, bot_id: str) -> TelegramConfig | None:
    return db.scalar(select(TelegramConfig).where(TelegramConfig.bot_id == bot_id))


def all_configured(db: Session) -> list[TelegramConfig]:
    return list(
        db.scalars(select(TelegramConfig).where(TelegramConfig.bot_token_encrypted.is_not(None)))
    )


def save_token(
    db: Session, bot_id: str, secret_key: str, token: str, username: str
) -> TelegramConfig:
    row = get(db, bot_id)
    if row is None:
        row = TelegramConfig(bot_id=bot_id)
        db.add(row)
    elif row.bot_username != username:
        row.chat_id = None  # a different bot: the old link no longer applies
        row.last_update_id = None
    row.bot_token_encrypted = encrypt_secret(secret_key, token, info=TELEGRAM_INFO)
    row.bot_token_last4 = token[-4:]
    row.bot_username = username
    row.error = None
    row.updated_at = utcnow()
    db.flush()
    return row


def token(row: TelegramConfig | None, secret_key: str) -> str | None:
    if row is None or not row.bot_token_encrypted:
        return None
    return decrypt_secret(secret_key, row.bot_token_encrypted, info=TELEGRAM_INFO)


def client_for(row: TelegramConfig | None, secret_key: str) -> TelegramClient | None:
    t = token(row, secret_key)
    return TelegramClient(t) if t else None


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def new_link_code(
    db: Session, row: TelegramConfig, now: datetime | None = None
) -> tuple[str, datetime]:
    """One-time code for the /start deep link; only its hash is stored."""
    code = secrets.token_urlsafe(24)[:CODE_LEN]
    expires = (now or utcnow()) + LINK_TTL
    row.link_code_hash = _hash(code)
    row.link_code_expires_at = expires
    row.updated_at = utcnow()
    db.flush()
    return code, expires


def consume_link_code(
    db: Session, row: TelegramConfig, code: str, chat_id: str, now: datetime | None = None
) -> bool:
    """Link chat_id if code matches and hasn't expired; the code works once."""
    now = now or utcnow()
    if (
        not row.link_code_hash
        or row.link_code_expires_at is None
        or row.link_code_expires_at <= now
        or not secrets.compare_digest(row.link_code_hash, _hash(code))
    ):
        return False
    row.chat_id = str(chat_id)
    row.link_code_hash = None
    row.link_code_expires_at = None
    row.updated_at = now
    db.flush()
    return True


def forget(db: Session, row: TelegramConfig) -> None:
    """Unlink and forget the token (keeps toggles so reconnecting restores them)."""
    row.bot_token_encrypted = None
    row.bot_token_last4 = None
    row.bot_username = None
    row.chat_id = None
    row.link_code_hash = None
    row.link_code_expires_at = None
    row.last_update_id = None
    row.webhook_secret = None
    row.mode = "polling"
    row.lease_owner = None
    row.lease_expires_at = None
    row.error = None
    row.updated_at = utcnow()
    db.flush()


def try_lease(
    db: Session, bot_id: str, owner: str, ttl: timedelta, now: datetime | None = None
) -> bool:
    """Take or renew the poller lease. A conditional UPDATE, so of two processes
    racing only one gets rowcount 1."""
    now = now or utcnow()
    t = TelegramConfig.__table__
    result = db.execute(
        update(t)
        .where(
            t.c.bot_id == bot_id,
            (t.c.lease_owner.is_(None)) | (t.c.lease_owner == owner) | (t.c.lease_expires_at < now),
        )
        .values(lease_owner=owner, lease_expires_at=now + ttl)
    )
    db.commit()
    return result.rowcount == 1


def release_lease(db: Session, bot_id: str, owner: str) -> None:
    t = TelegramConfig.__table__
    db.execute(
        update(t)
        .where(t.c.bot_id == bot_id, t.c.lease_owner == owner)
        .values(lease_owner=None, lease_expires_at=None)
    )
    db.commit()
