"""contact channels: profile_links gains kind + share, url becomes value

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-16

profile_identity.email_public / phone_public are kept but no longer used: their values
become channels here (email shared, phone NOT shared).
"""

import re
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_HOSTS = (
    ("linkedin", "linkedin.com"),
    ("github", "github.com"),
    ("instagram", "instagram.com"),
)


def _kind_for(url: str) -> str:
    m = re.match(r"^https?://([^/\s?#]+)", url.strip(), re.IGNORECASE)
    host = (m.group(1) if m else "").lower().removeprefix("www.")
    for kind, domain in _HOSTS:
        if host == domain or host.endswith("." + domain):
            return kind
    return "website"


def upgrade() -> None:
    with op.batch_alter_table("profile_links") as b:
        b.alter_column("url", new_column_name="value")
        b.add_column(sa.Column("kind", sa.Text, nullable=False, server_default="website"))
        b.add_column(sa.Column("share", sa.Boolean, nullable=False, server_default=sa.true()))

    conn = op.get_bind()
    links = sa.table(
        "profile_links",
        sa.column("id", sa.Text),
        sa.column("bot_id", sa.Text),
        sa.column("sort_order", sa.Integer),
        sa.column("label", sa.Text),
        sa.column("value", sa.Text),
        sa.column("kind", sa.Text),
        sa.column("share", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
    )
    for row in conn.execute(sa.select(links.c.id, links.c.value)).all():
        conn.execute(links.update().where(links.c.id == row.id).values(kind=_kind_for(row.value)))

    ident = sa.table(
        "profile_identity",
        sa.column("bot_id", sa.Text),
        sa.column("email_public", sa.Text),
        sa.column("phone_public", sa.Text),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(UTC)
    for i in conn.execute(
        sa.select(ident.c.bot_id, ident.c.email_public, ident.c.phone_public).where(
            ident.c.deleted_at.is_(None)
        )
    ).all():
        for kind, label, value, share in (
            ("email", "Email", i.email_public, True),
            ("phone", "Phone", i.phone_public, False),  # a number is never shared by default
        ):
            value = (value or "").strip()
            if not value:
                continue
            have = conn.execute(
                sa.select(links.c.id).where(
                    links.c.bot_id == i.bot_id,
                    links.c.kind == kind,
                    links.c.deleted_at.is_(None),
                )
            ).first()
            if have:  # idempotent: never add a second channel of the same kind
                continue
            top = conn.execute(
                sa.select(sa.func.max(links.c.sort_order)).where(
                    links.c.bot_id == i.bot_id, links.c.deleted_at.is_(None)
                )
            ).scalar()
            conn.execute(
                links.insert().values(
                    id=str(uuid.uuid4()),
                    bot_id=i.bot_id,
                    sort_order=0 if top is None else top + 1,
                    label=label,
                    value=value,
                    kind=kind,
                    share=share,
                    created_at=now,
                    updated_at=now,
                )
            )


def downgrade() -> None:
    # Only plain URL links survive a downgrade; email/phone/handle channels would not fit.
    op.execute("DELETE FROM profile_links WHERE kind IN ('email', 'phone', 'whatsapp')")
    with op.batch_alter_table("profile_links") as b:
        b.drop_column("share")
        b.drop_column("kind")
        b.alter_column("value", new_column_name="url")
