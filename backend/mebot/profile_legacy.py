"""Copy the pre-0005 free-text profile into the structured tables (used by 0005).

Idempotent: bots that already have a notes / identity row are skipped, so owner edits
are never overwritten. Uses lightweight table definitions (not the ORM models) so it
keeps working as those models grow.
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from mebot.models import new_id
from mebot.prompt import DEFAULT_PROFILE

_TS = sa.DateTime(timezone=True)
_notes = sa.table(
    "profile_notes",
    sa.column("id"),
    sa.column("bot_id"),
    sa.column("content"),
    sa.column("created_at", _TS),
    sa.column("updated_at", _TS),
)
_identity = sa.table(
    "profile_identity",
    sa.column("id"),
    sa.column("bot_id"),
    sa.column("full_name"),
    sa.column("created_at", _TS),
    sa.column("updated_at", _TS),
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def copy_legacy_profiles(conn: Connection) -> None:
    tables = set(sa.inspect(conn).get_table_names())
    source = "profiles" if "profiles" in tables else "legacy_profiles"
    have_notes = set(conn.execute(sa.text("SELECT bot_id FROM profile_notes")).scalars())
    have_identity = set(conn.execute(sa.text("SELECT bot_id FROM profile_identity")).scalars())
    now = _now()

    if source in tables:
        for bot_id, content in conn.execute(sa.text(f"SELECT bot_id, content FROM {source}")):
            text = (content or "").strip()
            # The untouched template carries no information; do not keep it as notes.
            if not text or text == DEFAULT_PROFILE.strip() or bot_id in have_notes:
                continue
            conn.execute(
                _notes.insert().values(
                    id=new_id(), bot_id=bot_id, content=content, created_at=now, updated_at=now
                )
            )
            have_notes.add(bot_id)

    # Only bots an owner has set up: "Default" is a placeholder, not a person.
    named = conn.execute(
        sa.text(
            "SELECT id, name FROM bots WHERE deleted_at IS NULL AND setup_completed_at IS NOT NULL"
        )
    )
    for bot_id, name in named:
        if bot_id in have_identity or not (name or "").strip():
            continue
        conn.execute(
            _identity.insert().values(
                id=new_id(), bot_id=bot_id, full_name=name.strip(), created_at=now, updated_at=now
            )
        )
