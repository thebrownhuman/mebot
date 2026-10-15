"""One-off import of the prototype's single-tenant tables (renamed legacy_* by 0001).

Safe to run repeatedly: rows already copied (matched by deterministic id) are skipped.
Legacy tables are left in place, never dropped.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from mebot.models import Bot, new_id, utcnow

DEFAULT_SLUG = "default"
DEFAULT_NAME = "Default"
_NS = uuid.UUID("6a1f6f3e-6d2c-4c8e-9d0a-6d6562f74c00")


def _legacy_id(table: str, old_id) -> str:
    return str(uuid.uuid5(_NS, f"{table}:{old_id}"))


def _dt(epoch: float | None) -> datetime:
    return datetime.fromtimestamp(epoch, UTC) if epoch is not None else utcnow()


# Columns of `bots` as of migration 0002. The ORM table has later columns (0003+), and
# this runs inside 0002, so inserting through Bot.__table__ would name columns that
# don't exist yet.
_BOTS_0002 = sa.table(
    "bots",
    sa.column("id"),
    sa.column("slug"),
    sa.column("name"),
    sa.column("created_at", Bot.__table__.c.created_at.type),
    sa.column("updated_at", Bot.__table__.c.updated_at.type),
)


# profiles as of 0002 (renamed legacy_profiles by 0005; no ORM model any more).
_PROFILES_0002 = sa.table(
    "profiles",
    sa.column("id"),
    sa.column("bot_id"),
    sa.column("content"),
    sa.column("created_at", Bot.__table__.c.created_at.type),
    sa.column("updated_at", Bot.__table__.c.updated_at.type),
)


_TS = Bot.__table__.c.created_at.type
# The other tables as of 0002, for the same reason.
_SESSIONS_0002 = sa.table(
    "sessions",
    sa.column("id"),
    sa.column("bot_id"),
    sa.column("recruiter_name"),
    sa.column("started_at", _TS),
    sa.column("created_at", _TS),
)
_MESSAGES_0002 = sa.table(
    "messages",
    sa.column("id"),
    sa.column("bot_id"),
    sa.column("session_id"),
    sa.column("role"),
    sa.column("content"),
    sa.column("created_at", _TS),
)
_ACCESS_LOG_0002 = sa.table(
    "access_log",
    sa.column("id"),
    sa.column("bot_id"),
    sa.column("session_id"),
    sa.column("event"),
    sa.column("detail"),
    sa.column("ip"),
    sa.column("created_at", _TS),
)


def ensure_default_bot(conn: Connection) -> str:
    bots = _BOTS_0002
    row = conn.execute(sa.select(bots.c.id).where(bots.c.slug == DEFAULT_SLUG)).first()
    if row:
        return row.id
    bot_id = new_id()
    now = utcnow()
    conn.execute(
        bots.insert().values(
            id=bot_id, slug=DEFAULT_SLUG, name=DEFAULT_NAME, created_at=now, updated_at=now
        )
    )
    return bot_id


def _existing_ids(conn: Connection, table: sa.Table) -> set[str]:
    return set(conn.execute(sa.select(table.c.id)).scalars())


def import_legacy(conn: Connection) -> dict[str, int]:
    tables = set(sa.inspect(conn).get_table_names())
    legacy = {
        t for t in ("profile", "sessions", "messages", "access_log") if f"legacy_{t}" in tables
    }
    copied = {"profiles": 0, "sessions": 0, "messages": 0, "access_log": 0}
    if not legacy:
        return copied
    bot_id = ensure_default_bot(conn)

    # After 0005 the profiles table is renamed; its data already moved to profile_notes.
    if "profile" in legacy and "profiles" in tables:
        profiles = _PROFILES_0002
        has_profile = conn.execute(
            sa.select(profiles.c.id).where(profiles.c.bot_id == bot_id)
        ).first()
        row = conn.execute(
            sa.text("SELECT content, updated_at FROM legacy_profile ORDER BY id LIMIT 1")
        ).first()
        if row and not has_profile:
            ts = _dt(row.updated_at)
            conn.execute(
                profiles.insert().values(
                    id=_legacy_id("profile", 1),
                    bot_id=bot_id,
                    content=row.content,
                    created_at=ts,
                    updated_at=ts,
                )
            )
            copied["profiles"] = 1

    if "sessions" in legacy:
        t = _SESSIONS_0002
        seen = _existing_ids(conn, t)
        rows = [
            dict(
                id=r.id,
                bot_id=bot_id,
                recruiter_name=r.recruiter_name,
                started_at=_dt(r.started_at),
                created_at=_dt(r.started_at),
            )
            for r in conn.execute(
                sa.text("SELECT id, recruiter_name, started_at FROM legacy_sessions")
            )
            if r.id not in seen
        ]
        if rows:
            conn.execute(t.insert(), rows)
        copied["sessions"] = len(rows)

    if "messages" in legacy:
        t = _MESSAGES_0002
        seen = _existing_ids(conn, t)
        rows = []
        for r in conn.execute(
            sa.text("SELECT id, session_id, role, content, ts FROM legacy_messages ORDER BY id")
        ):
            mid = _legacy_id("messages", r.id)
            if mid not in seen:
                rows.append(
                    dict(
                        id=mid,
                        bot_id=bot_id,
                        session_id=r.session_id,
                        role=r.role,
                        content=r.content,
                        created_at=_dt(r.ts),
                    )
                )
        if rows:
            conn.execute(t.insert(), rows)
        copied["messages"] = len(rows)

    if "access_log" in legacy:
        t = _ACCESS_LOG_0002
        seen = _existing_ids(conn, t)
        rows = []
        for r in conn.execute(
            sa.text("SELECT id, session_id, event, detail, ip, ts FROM legacy_access_log")
        ):
            lid = _legacy_id("access_log", r.id)
            if lid not in seen:
                rows.append(
                    dict(
                        id=lid,
                        bot_id=bot_id,
                        session_id=r.session_id,
                        event=r.event,
                        detail=r.detail,
                        ip=r.ip,
                        created_at=_dt(r.ts),
                    )
                )
        if rows:
            conn.execute(t.insert(), rows)
        copied["access_log"] = len(rows)

    return copied
