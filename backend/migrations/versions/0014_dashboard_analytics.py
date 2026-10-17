"""dashboard analytics: bots.timezone, bots.retention_days, query indexes

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-17

``bots.timezone`` replaces ``telegram_configs.timezone`` as the one zone for every
"today" / per-day bucket (the old column stays, unused). ``bots.retention_days`` is the
conversation retention window: existing bots keep their data (NULL = forever), new bots
default to 180 days in the application layer.
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_sessions_bot_id_started_at", "sessions", ["bot_id", "started_at"]),
    ("ix_messages_bot_id_created_at", "messages", ["bot_id", "created_at"]),
    (
        "ix_access_log_bot_id_event_created_at",
        "access_log",
        ["bot_id", "event", "created_at"],
    ),
    ("ix_access_log_session_id", "access_log", ["session_id"]),
)


def upgrade() -> None:
    op.add_column("bots", sa.Column("timezone", sa.Text, nullable=False, server_default="UTC"))
    op.add_column("bots", sa.Column("retention_days", sa.Integer, nullable=True))
    op.execute(
        "UPDATE bots SET timezone = COALESCE("
        "(SELECT t.timezone FROM telegram_configs t "
        "WHERE t.bot_id = bots.id AND t.timezone IS NOT NULL AND t.timezone <> ''), 'UTC')"
    )
    for name, table, cols in INDEXES:
        op.create_index(name, table, cols)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table)
    with op.batch_alter_table("bots") as batch:
        batch.drop_column("retention_days")
        batch.drop_column("timezone")
