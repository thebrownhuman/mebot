"""platform operator: platform_admins, platform_sessions, platform_audit, bots.approved_at

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-17

The operator is a separate role from tenant admins and has no bot. Their sessions live in
their own table (own cookie), and every operator action is written to platform_audit.
bots.approved_at records when an invite-mode sign-up was approved from the queue.
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_admins",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ux_platform_admins_email", "platform_admins", ["email"], unique=True)
    op.create_table(
        "platform_sessions",
        sa.Column("id", sa.Text, primary_key=True),  # sha256(token) hex
        sa.Column("platform_admin_id", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_platform_sessions_admin", "platform_sessions", ["platform_admin_id"])
    op.create_table(
        "platform_audit",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("actor_id", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("target_bot_id", sa.Text, nullable=True),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_platform_audit_created_at", "platform_audit", ["created_at"])
    op.add_column("bots", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("bots") as batch:
        batch.drop_column("approved_at")
    op.drop_table("platform_audit")
    op.drop_table("platform_sessions")
    op.drop_table("platform_admins")
