import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mebot.models import WidgetSettings, utcnow


def _get(db: Session, bot_id: str) -> WidgetSettings | None:
    return db.scalar(select(WidgetSettings).where(WidgetSettings.bot_id == bot_id))


def get_or_create(db: Session, bot_id: str) -> WidgetSettings:
    """The bot's widget row; created (and committed) with the defaults on first use."""
    row = _get(db, bot_id)
    if row is None:
        try:
            row = WidgetSettings(bot_id=bot_id)
            db.add(row)
            db.commit()
        except IntegrityError:  # another request created it concurrently
            db.rollback()
            row = _get(db, bot_id)
    return row


def origins(row: WidgetSettings) -> list[str]:
    return _list(row.allowed_origins)


def questions(row: WidgetSettings) -> list[str]:
    return _list(row.suggested_questions)


def _list(raw: str | None) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except ValueError:
        return []
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def update(db: Session, row: WidgetSettings, values: dict) -> WidgetSettings:
    for k, v in values.items():
        if k in ("allowed_origins", "suggested_questions"):
            v = json.dumps(v)
        setattr(row, k, v)
    row.updated_at = utcnow()
    db.flush()
    return row
