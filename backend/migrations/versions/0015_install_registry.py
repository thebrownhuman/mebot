"""install registry: telemetry_state, bots.update_contact_email, dismissed_update_version

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-17

``telemetry_state`` holds a single row: what this install last sent to the registry and
what it heard back (latest version, advisories).
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("update_contact_email", sa.Text, nullable=True))
    op.add_column("bots", sa.Column("dismissed_update_version", sa.Text, nullable=True))
    op.create_table(
        "telemetry_state",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registered_fingerprint", sa.Text, nullable=True),
        sa.Column("unregister_pending", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_register_error", sa.Text, nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_payload", sa.Text, nullable=True),
        sa.Column("last_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_version", sa.Text, nullable=True),
        sa.Column("min_supported", sa.Text, nullable=True),
        sa.Column("advisories", sa.Text, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("telemetry_state")
    with op.batch_alter_table("bots") as batch:
        batch.drop_column("dismissed_update_version")
        batch.drop_column("update_contact_email")
