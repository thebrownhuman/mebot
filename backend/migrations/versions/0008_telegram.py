"""telegram notifications: config, outbox, contacts; messages.from_owner

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _flag(name: str, default: bool) -> sa.Column:
    return sa.Column(
        name, sa.Boolean, nullable=False, server_default=sa.true() if default else sa.false()
    )


def upgrade() -> None:
    op.create_table(
        "telegram_configs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        # Fernet (HKDF info "mebot-telegram"); the plaintext token is never stored.
        sa.Column("bot_token_encrypted", sa.Text, nullable=True),
        sa.Column("bot_token_last4", sa.Text, nullable=True),
        sa.Column("bot_username", sa.Text, nullable=True),
        sa.Column("chat_id", sa.Text, nullable=True),
        sa.Column("link_code_hash", sa.Text, nullable=True),
        _ts("link_code_expires_at", nullable=True),
        _flag("enabled", True),
        sa.Column("mode", sa.Text, nullable=False, server_default="polling"),
        sa.Column("webhook_secret", sa.Text, nullable=True),
        sa.Column("last_update_id", sa.BigInteger, nullable=True),
        _flag("notify_new_session", True),
        _flag("notify_every_question", False),
        _flag("notify_unanswered", True),
        _flag("notify_contact", True),
        _flag("notify_limits", True),
        _flag("daily_digest", True),
        sa.Column("digest_hour", sa.Integer, nullable=False, server_default="21"),
        sa.Column("timezone", sa.Text, nullable=False, server_default="UTC"),
        sa.Column("last_digest_date", sa.Text, nullable=True),  # owner-local ISO date
        # Limit-alert dedup: >=80% cap once per UTC day, leak blocked at most hourly.
        sa.Column("last_cap_alert_date", sa.Text, nullable=True),
        _ts("last_leak_alert_at", nullable=True),
        # Poller lease: only the holder (process id) polls; renewed by heartbeat.
        sa.Column("lease_owner", sa.Text, nullable=True),
        _ts("lease_expires_at", nullable=True),
        # Set when Telegram rejects the token (revoked); shown as an admin banner.
        sa.Column("error", sa.Text, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ux_telegram_configs_bot_id", "telegram_configs", ["bot_id"], unique=True)

    op.create_table(
        "notifications",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("payload", sa.Text, nullable=False),  # JSON
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        _ts("next_attempt_at"),
        sa.Column("telegram_message_id", sa.BigInteger, nullable=True),
        sa.Column("session_id", sa.Text, nullable=True),
        sa.Column("ref_message_id", sa.Text, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index(
        "ix_notifications_status_next_attempt_at", "notifications", ["status", "next_attempt_at"]
    )
    op.create_index("ix_notifications_bot_id", "notifications", ["bot_id"])
    op.create_index(
        "ix_notifications_telegram_message_id", "notifications", ["telegram_message_id"]
    )

    op.create_table(
        "contacts",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        sa.Column("session_id", sa.Text, nullable=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("company", sa.Text, nullable=True),
        sa.Column("role", sa.Text, nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        _ts("created_at"),
        _ts("deleted_at", nullable=True),
    )
    op.create_index("ix_contacts_bot_id_deleted_at", "contacts", ["bot_id", "deleted_at"])

    with op.batch_alter_table("messages") as b:
        b.add_column(sa.Column("from_owner", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("messages") as b:
        b.drop_column("from_owner")
    op.drop_table("contacts")
    op.drop_table("notifications")
    op.drop_table("telegram_configs")
