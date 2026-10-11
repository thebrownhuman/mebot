from sqlalchemy import select
from sqlalchemy.orm import Session

from mebot.legacy import DEFAULT_NAME, DEFAULT_SLUG
from mebot.models import Bot


def get_by_slug(db: Session, slug: str) -> Bot | None:
    return db.scalar(select(Bot).where(Bot.slug == slug, Bot.deleted_at.is_(None)))


def create(db: Session, slug: str, name: str) -> Bot:
    bot = Bot(slug=slug, name=name)
    db.add(bot)
    db.flush()
    return bot


def get_or_create_default(db: Session) -> Bot:
    bot = get_by_slug(db, DEFAULT_SLUG)
    if bot is None:
        bot = create(db, DEFAULT_SLUG, DEFAULT_NAME)
        db.commit()
    return bot
