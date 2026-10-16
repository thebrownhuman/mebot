"""integration tokens: the optional GitHub token for imports (encrypted)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-17

One row per (bot, provider). The token is encrypted with SECRET_KEY like LLM keys;
only the last 4 characters are ever shown again.
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_tokens",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("token_encrypted", sa.Text, nullable=False),
        sa.Column("token_last4", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ux_integration_tokens_bot_provider",
        "integration_tokens",
        ["bot_id", "provider"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_integration_tokens_bot_provider", "integration_tokens")
    op.drop_table("integration_tokens")
