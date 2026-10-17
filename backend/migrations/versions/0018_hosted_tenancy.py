"""hosted tenancy: bot public key/status/plan, verification, resets, invites, redirects

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-17

- bots.public_key: opaque id for widget embeds (renaming the slug doesn't break them).
- bots.status: active | suspended | deleted; status_reason is operator-only.
- bots.plan: billing hook (#16), default "free".
- admins.email_verified_at: existing owners are backfilled as verified.
- admin_sessions.bot_id: sessions bind to the tenant they were created for.
- password_resets / email_verifications: single-use tokens, sha256 stored only.
- invites: codes for SIGNUP_MODE=invite, sha256 stored only.
- slug_redirects: old slug -> bot for 30 days after a rename.
"""

import secrets

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def _token_table(name: str) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.Text, primary_key=True),  # sha256(token) hex
        sa.Column("admin_id", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(f"ix_{name}_admin_id", name, ["admin_id"])


def upgrade() -> None:
    with op.batch_alter_table("bots") as batch:
        batch.add_column(sa.Column("public_key", sa.Text, nullable=True))
        batch.add_column(
            sa.Column("status", sa.Text, nullable=False, server_default="active")
        )
        batch.add_column(sa.Column("status_reason", sa.Text, nullable=True))
        batch.add_column(sa.Column("plan", sa.Text, nullable=False, server_default="free"))
        batch.add_column(
            sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True)
        )
    conn = op.get_bind()
    for (bot_id,) in conn.execute(sa.text("SELECT id FROM bots")).all():
        conn.execute(
            sa.text("UPDATE bots SET public_key = :k WHERE id = :id"),
            {"k": "pk_" + secrets.token_hex(12), "id": bot_id},
        )
    with op.batch_alter_table("bots") as batch:
        batch.alter_column("public_key", existing_type=sa.Text, nullable=False)
        batch.create_index("ux_bots_public_key", ["public_key"], unique=True)

    op.add_column("admins", sa.Column("email_verified_at", sa.DateTime(timezone=True)))
    conn.execute(sa.text("UPDATE admins SET email_verified_at = created_at"))
    op.add_column("admin_sessions", sa.Column("bot_id", sa.Text, nullable=True))

    _token_table("password_resets")
    _token_table("email_verifications")
    op.create_table(
        "invites",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("code_hash", sa.Text, nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_admin_id", sa.Text, nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ux_invites_code_hash", "invites", ["code_hash"], unique=True)
    op.create_table(
        "slug_redirects",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("old_slug", sa.Text, nullable=False),
        sa.Column("bot_id", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ux_slug_redirects_old_slug", "slug_redirects", ["old_slug"], unique=True)
    op.create_index("ix_slug_redirects_bot_id", "slug_redirects", ["bot_id"])


def downgrade() -> None:
    op.drop_table("slug_redirects")
    op.drop_table("invites")
    op.drop_table("email_verifications")
    op.drop_table("password_resets")
    with op.batch_alter_table("admin_sessions") as batch:
        batch.drop_column("bot_id")
    with op.batch_alter_table("admins") as batch:
        batch.drop_column("email_verified_at")
    with op.batch_alter_table("bots") as batch:
        batch.drop_index("ux_bots_public_key")
        for col in ("deletion_requested_at", "plan", "status_reason", "status", "public_key"):
            batch.drop_column(col)
