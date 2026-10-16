"""import jobs: resume / LinkedIn (and later GitHub) imports awaiting review

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-17

`kind` is free TEXT (validated in code) so new importers need no schema change.
Uploaded files are never stored; `draft` / `source_text` are nulled on expiry and the
row is kept as `expired`.
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_jobs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("filename", sa.Text, nullable=True),
        sa.Column("sha256", sa.Text, nullable=True),
        sa.Column("size_bytes", sa.Integer, nullable=True),
        sa.Column("draft", sa.Text, nullable=True),
        sa.Column("source_text", sa.Text, nullable=True),
        sa.Column("error_code", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("applied_summary", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_import_jobs_bot_id_created_at", "import_jobs", ["bot_id", "created_at"])
    op.create_index("ix_import_jobs_bot_id_sha256", "import_jobs", ["bot_id", "sha256"])


def downgrade() -> None:
    op.drop_index("ix_import_jobs_bot_id_sha256", "import_jobs")
    op.drop_index("ix_import_jobs_bot_id_created_at", "import_jobs")
    op.drop_table("import_jobs")
