"""structured profile tables; old profiles blob -> profile_notes

Renames profiles -> legacy_profiles (kept, not dropped) after copying each bot's
content into profile_notes and pre-filling profile_identity.full_name.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

from mebot.profile_legacy import copy_legacy_profiles

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

T = sa.Text
REQ = False  # nullable=False
OPT = True  # nullable=True


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _table(name: str, cols: list[tuple], *, singleton: bool = False) -> None:
    columns = [sa.Column("id", T, primary_key=True), sa.Column("bot_id", T, nullable=False)]
    if not singleton:
        columns.append(sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"))
    for cname, ctype, nullable, *default in cols:
        kw = {"server_default": default[0]} if default else {}
        columns.append(sa.Column(cname, ctype, nullable=nullable, **kw))
    columns += [_ts("created_at"), _ts("updated_at"), _ts("deleted_at", nullable=True)]
    op.create_table(name, *columns)
    op.create_index(f"ix_{name}_bot_id_deleted_at", name, ["bot_id", "deleted_at"])
    if singleton:
        op.create_index(f"ux_{name}_bot_id", name, ["bot_id"], unique=True)


def upgrade() -> None:
    _table(
        "profile_identity",
        [
            ("full_name", T, REQ, ""),
            ("headline", T, REQ, ""),
            ("location", T, REQ, ""),
            ("open_to", T, REQ, ""),
            ("summary", T, REQ, ""),
            ("email_public", T, OPT),
            ("phone_public", T, OPT),
            ("notice_period", T, OPT),
            ("salary_expectation", T, OPT),
            ("work_authorization", T, OPT),
            ("photo_url", T, OPT),
        ],
        singleton=True,
    )
    _table("profile_notes", [("content", T, REQ, "")], singleton=True)
    _table("profile_links", [("label", T, REQ), ("url", T, REQ)])
    _table(
        "experiences",
        [
            ("company", T, REQ),
            ("title", T, REQ),
            ("employment_type", T, OPT),
            ("location", T, OPT),
            ("start_month", T, REQ),
            ("end_month", T, OPT),
            ("description", T, REQ, ""),
            ("highlights", T, REQ, "[]"),
            ("tech", T, REQ, "[]"),
        ],
    )
    _table(
        "educations",
        [
            ("institution", T, REQ),
            ("degree", T, REQ),
            ("field", T, OPT),
            ("start_month", T, REQ),
            ("end_month", T, OPT),
            ("grade", T, OPT),
            ("description", T, OPT),
        ],
    )
    _table(
        "skills",
        [
            ("name", T, REQ),
            ("category", T, OPT),
            ("level", T, OPT),
            ("years_override", sa.Float, OPT),
            ("notes", T, OPT),
        ],
    )
    _table(
        "projects",
        [
            ("name", T, REQ),
            ("tagline", T, OPT),
            ("summary", T, REQ, ""),
            ("problem", T, OPT),
            ("my_role", T, OPT),
            ("frontend", T, OPT),
            ("backend", T, OPT),
            ("infra", T, OPT),
            ("data_ai", T, OPT),
            ("highlights", T, REQ, "[]"),
            ("tech", T, REQ, "[]"),
            ("repo_url", T, OPT),
            ("live_url", T, OPT),
            ("start_month", T, OPT),
            ("end_month", T, OPT),
            ("status", T, OPT),
        ],
    )
    _table("interests", [("kind", T, REQ), ("name", T, REQ), ("description", T, OPT)])
    _table("faqs", [("question", T, REQ), ("answer", T, REQ)])
    _table("avoid_topics", [("topic", T, REQ), ("reply", T, OPT)])

    copy_legacy_profiles(op.get_bind())
    op.rename_table("profiles", "legacy_profiles")


def downgrade() -> None:
    op.rename_table("legacy_profiles", "profiles")
    for t in (
        "avoid_topics",
        "faqs",
        "interests",
        "projects",
        "skills",
        "educations",
        "experiences",
        "profile_links",
        "profile_notes",
        "profile_identity",
    ):
        op.drop_table(t)
