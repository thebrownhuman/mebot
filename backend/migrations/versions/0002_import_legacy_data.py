"""copy prototype (legacy_*) rows into the multi-bot tables under the default bot

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12
"""

from alembic import op

from mebot.legacy import import_legacy

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    import_legacy(op.get_bind())


def downgrade() -> None:
    # Imported rows are indistinguishable from new ones; legacy_* tables are kept
    # untouched, so nothing to undo here.
    pass
