from sqlalchemy import select
from sqlalchemy.orm import Session

from mebot.models import LLMConfig, utcnow

DEFAULT_TEMPERATURE = 0.4
DEFAULT_MAX_TOKENS = 600


def get(db: Session, bot_id: str) -> LLMConfig | None:
    return db.scalar(select(LLMConfig).where(LLMConfig.bot_id == bot_id))


def save(
    db: Session,
    bot_id: str,
    *,
    provider: str,
    model: str,
    base_url: str | None,
    api_key_encrypted: str | None,
    api_key_last4: str | None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> LLMConfig:
    """Create or overwrite the bot's config. Only called after a passing test call."""
    now = utcnow()
    cfg = get(db, bot_id)
    if cfg is None:
        cfg = LLMConfig(bot_id=bot_id, created_at=now)
        db.add(cfg)
    cfg.provider = provider
    cfg.model = model
    cfg.base_url = base_url
    cfg.api_key_encrypted = api_key_encrypted
    cfg.api_key_last4 = api_key_last4
    cfg.temperature = temperature
    cfg.max_tokens = max_tokens
    cfg.last_tested_at = now
    cfg.last_test_ok = True
    cfg.updated_at = now
    db.flush()
    return cfg


def record_test(db: Session, cfg: LLMConfig, ok: bool) -> None:
    cfg.last_tested_at = utcnow()
    cfg.last_test_ok = ok
    db.flush()
