from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mebot.legacy import DEFAULT_NAME, DEFAULT_SLUG
from mebot.models import Admin, Bot, utcnow


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
        try:
            bot = create(db, DEFAULT_SLUG, DEFAULT_NAME)
            db.commit()
        except IntegrityError:  # another request created it concurrently
            db.rollback()
            bot = get_by_slug(db, DEFAULT_SLUG)
    return bot


def get_primary(db: Session) -> Bot:
    """Single mode's bot: the one set up by the owner (it may have been renamed from
    `default`), else the `default` bot, created if missing."""
    bot = db.scalar(
        select(Bot)
        .where(Bot.setup_completed_at.is_not(None), Bot.deleted_at.is_(None))
        .order_by(Bot.created_at)
        .limit(1)
    )
    return bot or get_or_create_default(db)


def claim_setup(db: Session, bot: Bot) -> bool:
    """Atomically mark setup done for bot, only while no active admin exists.

    The conditional UPDATE takes the write lock first, so of two concurrent setups only
    one sees "no admin" and updates a row; the other gets rowcount 0.
    """
    no_admin = ~exists().where(Admin.deleted_at.is_(None))
    result = db.execute(
        update(Bot)
        .where(Bot.id == bot.id, no_admin)
        .values(setup_completed_at=utcnow(), updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1
