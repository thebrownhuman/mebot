"""Daily and per-session usage counters in the DB.

``consume`` increments several counters with one conditional upsert each, inside the
caller's transaction: the first write takes SQLite's write lock, so two requests racing
for the last slot are serialised and exactly one passes. On a refused scope the counters
already incremented in this call are decremented again (still under the same lock), so
a refused request consumes nothing.
"""

import hashlib
import hmac
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from mebot.models import UsageCounter, new_id, utcnow

SESSION_WINDOW = "-"
RETENTION = timedelta(days=7)
_KEY = ("bot_id", "scope", "key", "window_start")


def ip_hash(secret_key: str, ip: str | None) -> str:
    """HMAC-SHA256(SECRET_KEY, ip): stable per install, never reversible to the IP."""
    return hmac.new(secret_key.encode(), (ip or "?").encode(), hashlib.sha256).hexdigest()


def window_for(scope: str, day: date) -> str:
    return SESSION_WINDOW if scope == "session" else day.isoformat()


def _insert(db: Session):
    return pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert


def _bump(db: Session, bot_id: str, scope: str, key: str, window: str, limit: int) -> bool:
    now = utcnow()
    t = UsageCounter.__table__
    stmt = _insert(db)(t).values(
        id=new_id(),
        bot_id=bot_id,
        scope=scope,
        key=key,
        window_start=window,
        messages=1,
        tokens=0,
        estimated_tokens=0,
        created_at=now,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=list(_KEY),
        set_={"messages": t.c.messages + 1, "updated_at": now},
        where=t.c.messages < limit,
    ).returning(t.c.messages)
    return db.execute(stmt).first() is not None


def _unbump(db: Session, bot_id: str, scope: str, key: str, window: str) -> None:
    t = UsageCounter.__table__
    db.execute(
        update(t)
        .where(
            t.c.bot_id == bot_id,
            t.c.scope == scope,
            t.c.key == key,
            t.c.window_start == window,
        )
        .values(messages=t.c.messages - 1)
    )


def consume(db: Session, bot_id: str, items: list[tuple[str, str, int]], day: date) -> str | None:
    """Count one message in each (scope, key, limit), in order. Returns the first scope
    that is already at its limit (nothing is consumed then), or None."""
    done: list[tuple[str, str, str]] = []
    for scope, key, limit in items:
        window = window_for(scope, day)
        if not _bump(db, bot_id, scope, key, window, limit):
            for s, k, w in reversed(done):
                _unbump(db, bot_id, s, k, w)
            db.flush()
            return scope
        done.append((scope, key, window))
    return None


def release(db: Session, bot_id: str, items: list[tuple[str, str]], day: date) -> None:
    """Give back one message per (scope, key) consumed earlier in this transaction."""
    for scope, key in items:
        _unbump(db, bot_id, scope, key, window_for(scope, day))


def add_tokens(
    db: Session,
    bot_id: str,
    items: list[tuple[str, str]],
    day: date,
    tokens: int,
    *,
    estimated: bool,
    now: datetime | None = None,
) -> None:
    now = now or utcnow()
    est = tokens if estimated else 0
    t = UsageCounter.__table__
    for scope, key in items:
        stmt = _insert(db)(t).values(
            id=new_id(),
            bot_id=bot_id,
            scope=scope,
            key=key,
            window_start=window_for(scope, day),
            messages=0,
            tokens=tokens,
            estimated_tokens=est,
            created_at=now,
            updated_at=now,
        )
        db.execute(
            stmt.on_conflict_do_update(
                index_elements=list(_KEY),
                set_={
                    "tokens": t.c.tokens + tokens,
                    "estimated_tokens": t.c.estimated_tokens + est,
                    "updated_at": now,
                },
            )
        )


def get(db: Session, bot_id: str, scope: str, key: str, day: date) -> UsageCounter | None:
    db.flush()
    return db.scalar(
        select(UsageCounter)
        .where(
            UsageCounter.bot_id == bot_id,
            UsageCounter.scope == scope,
            UsageCounter.key == key,
            UsageCounter.window_start == window_for(scope, day),
        )
        .execution_options(populate_existing=True)
    )


def daily(db: Session, bot_id: str, since: date) -> list[UsageCounter]:
    return list(
        db.scalars(
            select(UsageCounter).where(
                UsageCounter.bot_id == bot_id,
                UsageCounter.scope.in_(("bot_day", "ip_day")),
                UsageCounter.window_start >= since.isoformat(),
            )
        )
    )


def purge(db: Session, now: datetime | None = None) -> int:
    """Hard-delete counters untouched for 7 days (operational data, not user data)."""
    cutoff = (now or utcnow()) - RETENTION
    return db.execute(delete(UsageCounter).where(UsageCounter.updated_at < cutoff)).rowcount
