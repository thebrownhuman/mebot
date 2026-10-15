from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mebot.models import BotLimits, utcnow


def _get(db: Session, bot_id: str) -> BotLimits | None:
    return db.scalar(select(BotLimits).where(BotLimits.bot_id == bot_id))


def get_or_create(db: Session, bot_id: str) -> BotLimits:
    """The bot's limits row; created (and committed) with the defaults on first use."""
    row = _get(db, bot_id)
    if row is None:
        try:
            row = BotLimits(bot_id=bot_id)
            db.add(row)
            db.commit()
        except IntegrityError:  # another request created it concurrently
            db.rollback()
            row = _get(db, bot_id)
    return row


def update(db: Session, row: BotLimits, values: dict) -> BotLimits:
    for k, v in values.items():
        setattr(row, k, v)
    row.updated_at = utcnow()
    db.flush()
    return row
