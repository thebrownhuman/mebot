"""widget settings: one row per bot

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "widget_settings",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        # JSON arrays stored as TEXT (SQLite-friendly, same as elsewhere in the schema).
        sa.Column("allowed_origins", sa.Text, nullable=False, server_default="[]"),
        sa.Column("allow_any_origin", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("primary_color", sa.Text, nullable=False, server_default="#0f766e"),
        sa.Column("theme", sa.Text, nullable=False, server_default="auto"),
        sa.Column("position", sa.Text, nullable=False, server_default="right"),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("avatar_url", sa.Text, nullable=True),
        sa.Column("launcher_label", sa.Text, nullable=True),
        sa.Column("suggested_questions", sa.Text, nullable=False, server_default="[]"),
        sa.Column("show_orb", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("auto_open_seconds", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ux_widget_settings_bot_id", "widget_settings", ["bot_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_widget_settings_bot_id", "widget_settings")
    op.drop_table("widget_settings")
