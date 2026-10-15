"""per-bot chat limits and usage counters

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _int(name: str, default: int) -> sa.Column:
    return sa.Column(name, sa.Integer, nullable=False, server_default=str(default))


def upgrade() -> None:
    op.create_table(
        "bot_limits",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        _int("per_ip_per_minute", 10),
        _int("per_ip_per_day", 100),
        _int("per_session_messages", 40),
        _int("sessions_per_ip_per_hour", 10),
        _int("daily_message_cap", 500),
        sa.Column("daily_token_cap", sa.Integer, nullable=True),  # NULL = off
        _int("max_message_chars", 1000),
        _int("history_turns", 12),
        sa.Column("paused", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("paused_message", sa.Text, nullable=True),
        sa.Column("turnstile_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ux_bot_limits_bot_id", "bot_limits", ["bot_id"], unique=True)

    # Operational data: rows are hard-deleted after 7 days (documented exception to
    # soft delete). `key` is an HMAC of the IP, a session id or "*", never a raw IP.
    op.create_table(
        "usage_counters",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        sa.Column("scope", sa.Text, nullable=False),  # ip_day | bot_day | session
        sa.Column("key", sa.Text, nullable=False),
        sa.Column("window_start", sa.Text, nullable=False),  # UTC date, or "-" for session
        _int("messages", 0),
        _int("tokens", 0),
        _int("estimated_tokens", 0),  # part of `tokens` that was estimated (chars/4)
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index(
        "ux_usage_counters_window",
        "usage_counters",
        ["bot_id", "scope", "key", "window_start"],
        unique=True,
    )
    op.create_index("ix_usage_counters_updated_at", "usage_counters", ["updated_at"])


def downgrade() -> None:
    op.drop_table("usage_counters")
    op.drop_table("bot_limits")
