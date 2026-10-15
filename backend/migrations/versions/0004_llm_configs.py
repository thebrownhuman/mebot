"""per-bot LLM provider configuration

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "llm_configs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("base_url", sa.Text, nullable=True),
        # Fernet token (key derived from SECRET_KEY); the plaintext key is never stored.
        sa.Column("api_key_encrypted", sa.Text, nullable=True),
        sa.Column("api_key_last4", sa.Text, nullable=True),
        sa.Column("temperature", sa.Float, nullable=False, server_default="0.4"),
        sa.Column("max_tokens", sa.Integer, nullable=False, server_default="600"),
        _ts("last_tested_at", nullable=True),
        sa.Column("last_test_ok", sa.Boolean, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ux_llm_configs_bot_id", "llm_configs", ["bot_id"], unique=True)


def downgrade() -> None:
    op.drop_table("llm_configs")
