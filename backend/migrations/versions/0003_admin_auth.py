"""admin accounts, admin sessions, setup state on bots

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "admins",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        # Unused in single mode (one admin owns the default bot); for hosted mode later.
        sa.Column("bot_id", sa.Text, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("deleted_at", nullable=True),
    )
    op.create_index("ux_admins_email", "admins", ["email"], unique=True)

    op.create_table(
        "admin_sessions",
        # SHA-256 hex of the cookie token; the raw token is never stored.
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("admin_id", sa.Text, nullable=False),
        _ts("created_at"),
        _ts("expires_at"),
        _ts("last_seen_at"),
        sa.Column("ip", sa.Text),
        sa.Column("user_agent", sa.Text),
    )
    op.create_index("ix_admin_sessions_admin_id", "admin_sessions", ["admin_id"])
    op.create_index("ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"])

    with op.batch_alter_table("bots") as b:
        b.add_column(
            sa.Column("registration_consent", sa.Boolean, nullable=False, server_default=sa.false())
        )
        b.add_column(_ts("setup_completed_at", nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("bots") as b:
        b.drop_column("setup_completed_at")
        b.drop_column("registration_consent")
    op.drop_table("admin_sessions")
    op.drop_table("admins")
