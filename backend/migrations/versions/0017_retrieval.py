"""retrieval for large profiles: knowledge_chunks, retrieval_settings, messages.chunk_ids

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        sa.Column("section", sa.Text, nullable=False),
        sa.Column("item_key", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        # float32 little-endian vector; NULL until embeddings are enabled and computed.
        sa.Column("embedding", sa.LargeBinary, nullable=True),
        sa.Column("embedding_model", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ux_knowledge_chunks_bot_id_item_key",
        "knowledge_chunks",
        ["bot_id", "item_key"],
        unique=True,
    )
    op.create_table(
        "retrieval_settings",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        sa.Column("mode", sa.Text, nullable=False, server_default="auto"),
        sa.Column("embeddings_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("embedding_model", sa.Text, nullable=True),
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ux_retrieval_settings_bot_id", "retrieval_settings", ["bot_id"], unique=True)
    with op.batch_alter_table("messages") as b:
        # JSON list of knowledge_chunks ids shown to the model for this reply (NULL = full profile).
        b.add_column(sa.Column("chunk_ids", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("messages") as b:
        b.drop_column("chunk_ids")
    op.drop_index("ux_retrieval_settings_bot_id", "retrieval_settings")
    op.drop_table("retrieval_settings")
    op.drop_index("ux_knowledge_chunks_bot_id_item_key", "knowledge_chunks")
    op.drop_table("knowledge_chunks")
