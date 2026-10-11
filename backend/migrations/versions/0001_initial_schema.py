"""initial multi-bot schema

If the prototype's tables (profile/sessions/messages/access_log without bot_id)
are present they are renamed to legacy_* first; 0002 copies their rows across.

Revision ID: 0001
Revises:
Create Date: 2026-10-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

LEGACY_TABLES = ("profile", "sessions", "messages", "access_log")


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _rename_legacy_tables() -> None:
    insp = sa.inspect(op.get_bind())
    existing = set(insp.get_table_names())
    for t in LEGACY_TABLES:
        if t not in existing:
            continue
        cols = {c["name"] for c in insp.get_columns(t)}
        if "bot_id" in cols:
            continue
        op.rename_table(t, f"legacy_{t}")


def upgrade() -> None:
    _rename_legacy_tables()

    op.create_table(
        "bots",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("slug", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("deleted_at", nullable=True),
    )
    op.create_index("ux_bots_slug", "bots", ["slug"], unique=True)

    op.create_table(
        "profiles",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        sa.Column("content", sa.Text),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ux_profiles_bot_id", "profiles", ["bot_id"], unique=True)

    op.create_table(
        "sessions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        sa.Column("recruiter_name", sa.Text),
        _ts("started_at"),
        _ts("created_at"),
    )
    op.create_index("ix_sessions_bot_id", "sessions", ["bot_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        sa.Column("session_id", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        _ts("created_at"),
    )
    op.create_index("ix_messages_bot_id", "messages", ["bot_id"])
    op.create_index("ix_messages_session_id_created_at", "messages", ["session_id", "created_at"])

    op.create_table(
        "access_log",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        sa.Column("session_id", sa.Text),
        sa.Column("event", sa.Text, nullable=False),
        sa.Column("detail", sa.Text),
        sa.Column("ip", sa.Text),
        _ts("created_at"),
    )
    op.create_index("ix_access_log_bot_id", "access_log", ["bot_id"])
    op.create_index("ix_access_log_bot_id_created_at", "access_log", ["bot_id", "created_at"])


def downgrade() -> None:
    for t in ("access_log", "messages", "sessions", "profiles", "bots"):
        op.drop_table(t)
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for t in LEGACY_TABLES:
        if f"legacy_{t}" in existing:
            op.rename_table(f"legacy_{t}", t)
