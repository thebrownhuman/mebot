"""experience-count toggles on profile_identity; messages.unanswered

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("profile_identity") as b:
        b.add_column(
            sa.Column("count_internships", sa.Boolean, nullable=False, server_default=sa.false())
        )
        b.add_column(
            sa.Column("count_freelance", sa.Boolean, nullable=False, server_default=sa.true())
        )
    with op.batch_alter_table("messages") as b:
        b.add_column(sa.Column("unanswered", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("messages") as b:
        b.drop_column("unanswered")
    with op.batch_alter_table("profile_identity") as b:
        b.drop_column("count_freelance")
        b.drop_column("count_internships")
