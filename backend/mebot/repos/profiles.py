from sqlalchemy import select
from sqlalchemy.orm import Session

from mebot.models import Profile, utcnow
from mebot.prompt import DEFAULT_PROFILE


def get_content(db: Session, bot_id: str) -> str:
    content = db.scalar(select(Profile.content).where(Profile.bot_id == bot_id))
    return content if content is not None else DEFAULT_PROFILE


def save(db: Session, bot_id: str, content: str) -> None:
    profile = db.scalar(select(Profile).where(Profile.bot_id == bot_id))
    if profile is None:
        db.add(Profile(bot_id=bot_id, content=content))
    else:
        profile.content = content
        profile.updated_at = utcnow()
    db.flush()
