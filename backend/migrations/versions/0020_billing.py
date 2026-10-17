"""paid plans: plans, subscriptions, billing_events, invoices, trial_claims, admin terms

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-17

Billing is inert unless MODE=hosted and BILLING_PROVIDERS is set; on other installs these
tables stay empty (apart from the two seeded plans). No FKs; ids are TEXT.
"""

import json
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    plans = op.create_table(
        "plans",
        sa.Column("code", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_trial", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("prices", sa.Text, nullable=False, server_default="{}"),
        sa.Column("limits", sa.Text, nullable=False, server_default="{}"),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        sa.Column("provider", sa.Text),
        sa.Column("provider_customer_id", sa.Text),
        sa.Column("provider_subscription_id", sa.Text),
        sa.Column("plan_code", sa.Text),
        sa.Column("currency", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="none"),
        sa.Column("current_period_end", TS),
        sa.Column("cancel_at_period_end", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("grace_until", TS),
        sa.Column("trial_started_at", TS),
        sa.Column("trial_ends_at", TS),
        sa.Column("trial_messages_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("comp_until", TS),
        sa.Column("inactive_since", TS),
        sa.Column("notices", sa.Text, nullable=False, server_default=""),
        sa.Column("owner_gstin", sa.Text),
        sa.Column("updated_from_event_at", TS),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index("ux_subscriptions_bot_id", "subscriptions", ["bot_id"], unique=True)
    op.create_index(
        "ix_subscriptions_provider_sub", "subscriptions", ["provider", "provider_subscription_id"]
    )
    op.create_table(
        "billing_events",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("event_id", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("bot_id", sa.Text),
        sa.Column("payload", sa.Text),
        sa.Column("received_at", TS, nullable=False),
        sa.Column("processed_at", TS),
        sa.Column("error", sa.Text),
    )
    op.create_index(
        "ux_billing_events_provider_event", "billing_events", ["provider", "event_id"], unique=True
    )
    op.create_index("ix_billing_events_received_at", "billing_events", ["received_at"])
    op.create_table(
        "invoices",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("bot_id", sa.Text, nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("provider_invoice_id", sa.Text, nullable=False),
        sa.Column("amount_minor", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("currency", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("period_start", TS),
        sa.Column("period_end", TS),
        sa.Column("hosted_url", sa.Text),
        sa.Column("pdf_url", sa.Text),
        sa.Column("tax_minor", sa.BigInteger),
        sa.Column("gstin", sa.Text),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_index(
        "ux_invoices_provider_invoice", "invoices", ["provider_invoice_id"], unique=True
    )
    op.create_index("ix_invoices_bot_id", "invoices", ["bot_id"])
    op.create_table(
        "trial_claims",
        sa.Column("email_hash", sa.Text, primary_key=True),
        sa.Column("claimed_at", TS, nullable=False),
    )
    op.add_column("admins", sa.Column("terms_version", sa.Text, nullable=True))
    op.add_column("admins", sa.Column("terms_accepted_at", TS, nullable=True))

    # Seed plans; prices are filled in by the operator (CLI / platform panel).
    now = datetime.now(UTC)
    if op.get_bind().dialect.name == "sqlite":
        now = now.replace(tzinfo=None)
    op.bulk_insert(
        plans,
        [
            {
                "code": "trial", "name": "Free trial", "active": True, "is_trial": True,
                "prices": "{}", "limits": json.dumps({"daily_message_cap": 100}),
                "created_at": now, "updated_at": now,
            },
            {
                "code": "monthly", "name": "Monthly", "active": True, "is_trial": False,
                "prices": "{}", "limits": "{}", "created_at": now, "updated_at": now,
            },
        ],
    )  # fmt: skip


def downgrade() -> None:
    with op.batch_alter_table("admins") as batch:
        batch.drop_column("terms_accepted_at")
        batch.drop_column("terms_version")
    for t in ("trial_claims", "invoices", "billing_events", "subscriptions", "plans"):
        op.drop_table(t)
