"""Free-text profile, now stored as the bot's profile_notes row.

TODO(profile-pages): replaced by the structured profile API and renderer.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from mebot.models import ProfileNotes, utcnow
from mebot.prompt import DEFAULT_PROFILE


def _notes(db: Session, bot_id: str) -> ProfileNotes | None:
    return db.scalar(
        select(ProfileNotes).where(ProfileNotes.bot_id == bot_id, ProfileNotes.deleted_at.is_(None))
    )


def get_content(db: Session, bot_id: str) -> str:
    row = _notes(db, bot_id)
    return row.content if row is not None else DEFAULT_PROFILE


def save(db: Session, bot_id: str, content: str) -> None:
    row = _notes(db, bot_id)
    if row is None:
        db.add(ProfileNotes(bot_id=bot_id, content=content))
    else:
        row.content = content
        row.updated_at = utcnow()
    db.flush()
