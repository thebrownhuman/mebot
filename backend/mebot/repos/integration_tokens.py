"""Third-party tokens (GitHub for imports). Encrypted at rest; plaintext only in memory."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from mebot.crypto import decrypt_secret, encrypt_secret
from mebot.models import IntegrationToken, utcnow

# Separate key derivation from LLM keys: one leaked purpose doesn't open the other.
_INFO = b"mebot-integration-token-v1"


def get(db: Session, bot_id: str, provider: str) -> IntegrationToken | None:
    return db.scalar(
        select(IntegrationToken).where(
            IntegrationToken.bot_id == bot_id, IntegrationToken.provider == provider
        )
    )


def save(db: Session, secret_key: str, bot_id: str, provider: str, token: str) -> IntegrationToken:
    now = utcnow()
    row = get(db, bot_id, provider)
    if row is None:
        row = IntegrationToken(bot_id=bot_id, provider=provider, created_at=now)
        db.add(row)
    row.token_encrypted = encrypt_secret(secret_key, token, _INFO)
    row.token_last4 = token[-4:]
    row.updated_at = now
    db.flush()
    return row


def plaintext(db: Session, secret_key: str, bot_id: str, provider: str) -> str | None:
    row = get(db, bot_id, provider)
    return decrypt_secret(secret_key, row.token_encrypted, _INFO) if row else None


def delete(db: Session, bot_id: str, provider: str) -> bool:
    row = get(db, bot_id, provider)
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True
