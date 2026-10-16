"""learning loop: assistant persona columns (open questions and learned facts follow)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("profile_identity") as b:
        b.add_column(
            sa.Column("pronouns", sa.Text, nullable=False, server_default="they/them")
        )
        b.add_column(sa.Column("assistant_greeting", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("profile_identity") as b:
        b.drop_column("assistant_greeting")
        b.drop_column("pronouns")
