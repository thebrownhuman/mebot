"""learning loop: persona columns, open_questions, learned_facts

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


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    with op.batch_alter_table("profile_identity") as b:
        b.add_column(
            sa.Column("pronouns", sa.Text, nullable=False, server_default="they/them")
        )
        b.add_column(sa.Column("assistant_greeting", sa.Text, nullable=True))

    op.create_table(
        "open_questions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("normalized", sa.Text, nullable=False),
        sa.Column("ask_count", sa.Integer, nullable=False, server_default="1"),
        _ts("first_asked_at"),
        _ts("last_asked_at"),
        sa.Column("last_session_id", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column("answered_fact_id", sa.Text, nullable=True),
        _ts("last_notified_at", nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_open_questions_bot_id_status", "open_questions", ["bot_id", "status"])

    op.create_table(
        "learned_facts",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        sa.Column("open_question_id", sa.Text, nullable=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("answer_raw", sa.Text, nullable=False),
        sa.Column("fact_text", sa.Text, nullable=False),
        sa.Column("suggested_section", sa.Text, nullable=False, server_default="learned"),
        sa.Column("suggested_field", sa.Text, nullable=True),
        sa.Column("suggested_value", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("source", sa.Text, nullable=False, server_default="admin"),
        sa.Column("needs_review", sa.Boolean, nullable=False, server_default=sa.false()),
        _ts("approved_at", nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("deleted_at", nullable=True),
    )
    op.create_index(
        "ix_learned_facts_bot_id_status_deleted_at",
        "learned_facts",
        ["bot_id", "status", "deleted_at"],
    )


def downgrade() -> None:
    op.drop_table("learned_facts")
    op.drop_table("open_questions")
    with op.batch_alter_table("profile_identity") as b:
        b.drop_column("assistant_greeting")
        b.drop_column("pronouns")
