from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mebot.legacy import DEFAULT_NAME, DEFAULT_SLUG
from mebot.models import Admin, Bot, SlugRedirect, utcnow


def get_by_slug(db: Session, slug: str) -> Bot | None:
    return db.scalar(select(Bot).where(Bot.slug == slug, Bot.deleted_at.is_(None)))


def get(db: Session, bot_id: str) -> Bot | None:
    return db.scalar(select(Bot).where(Bot.id == bot_id, Bot.deleted_at.is_(None)))


def _live(db: Session, bot: Bot | None) -> Bot | None:
    """bot if it may answer the public: active, set up, owner e-mail verified."""
    if bot is None or bot.status != "active" or bot.deletion_requested_at is not None:
        return None
    if bot.setup_completed_at is None:
        return None
    owner = db.scalar(
        select(Admin).where(
            Admin.bot_id == bot.id,
            Admin.deleted_at.is_(None),
            Admin.email_verified_at.is_not(None),
        )
    )
    return bot if owner is not None else None


def get_live_by_slug(db: Session, slug: str) -> Bot | None:
    return _live(db, get_by_slug(db, slug))


def get_live_by_public_key(db: Session, key: str) -> Bot | None:
    bot = db.scalar(select(Bot).where(Bot.public_key == key, Bot.deleted_at.is_(None)))
    return _live(db, bot)


def redirect_target(db: Session, old_slug: str, now=None) -> Bot | None:
    """Bot an old slug still points to (kept for 30 days after a rename)."""
    row = db.scalar(
        select(SlugRedirect).where(
            SlugRedirect.old_slug == old_slug, SlugRedirect.expires_at > (now or utcnow())
        )
    )
    return get_live_by_slug_id(db, row.bot_id) if row else None


def get_live_by_slug_id(db: Session, bot_id: str) -> Bot | None:
    return _live(db, get(db, bot_id))


def slug_taken(db: Session, slug: str, now=None) -> bool:
    """Taken by a bot (any status, so a suspended tenant keeps it) or a live redirect."""
    if db.scalar(select(Bot.id).where(Bot.slug == slug).limit(1)) is not None:
        return True
    return (
        db.scalar(
            select(SlugRedirect.id).where(
                SlugRedirect.old_slug == slug, SlugRedirect.expires_at > (now or utcnow())
            )
        )
        is not None
    )


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
    one sees "no admin" (SQLite) / an unchanged row (Postgres) and updates it; the other
    gets rowcount 0.
    """
    no_admin = ~exists().where(Admin.deleted_at.is_(None))
    # Postgres (READ COMMITTED) re-checks only the locked row's own columns after waiting
    # for a concurrent claim, not the subquery: so also require the row to be unchanged
    # since we read it (optimistic check on setup_completed_at).
    seen = bot.setup_completed_at
    unchanged = Bot.setup_completed_at.is_(None) if seen is None else Bot.setup_completed_at == seen
    result = db.execute(
        update(Bot)
        .where(Bot.id == bot.id, no_admin, unchanged)
        .values(setup_completed_at=utcnow(), updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1
