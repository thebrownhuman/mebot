"""The bot's timezone: one IANA zone for every "today" / per-day bucket."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from mebot.models import Bot


def safe_zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def valid(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def bot_zone(db: Session, bot_id: str) -> ZoneInfo:
    return safe_zone(db.scalar(select(Bot.timezone).where(Bot.id == bot_id)))
