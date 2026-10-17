"""hash stored IPs: access_log.ip -> ip_hash, admin_sessions.ip -> ip_hash

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-17

Raw visitor/admin IPs are replaced in place with HMAC-SHA256(SECRET_KEY, ip), the same
hash usage_counters keys on. Rows are rewritten in batches of 1k so a large access_log
doesn't hold one long write lock. Values that already look hashed are left alone.
Downgrade only renames the columns back; the raw IPs are gone for good.
"""

import sqlalchemy as sa
from alembic import context, op

from mebot.limits.counters import hash_ip_value

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

TABLES = ("access_log", "admin_sessions")
BATCH = 1000


def _secret_key() -> str:
    key = context.config.attributes.get("secret_key")
    if key:
        return key
    from mebot.config import Settings, resolve_secret_key

    return resolve_secret_key(Settings())


def _hash_table(conn: sa.Connection, table: str, key_fn) -> None:
    t = sa.table(table, sa.column("id"), sa.column("ip"))
    last = ""
    key = None
    while True:
        rows = conn.execute(
            sa.select(t.c.id, t.c.ip)
            .where(t.c.id > last, t.c.ip.is_not(None))
            .order_by(t.c.id)
            .limit(BATCH)
        ).all()
        if not rows:
            return
        key = key or key_fn()
        conn.execute(
            t.update().where(t.c.id == sa.bindparam("rid")).values(ip=sa.bindparam("h")),
            [{"rid": r.id, "h": hash_ip_value(key, r.ip)} for r in rows],
        )
        last = rows[-1].id


def upgrade() -> None:
    conn = op.get_bind()
    for table in TABLES:
        _hash_table(conn, table, _secret_key)
        with op.batch_alter_table(table) as b:
            b.alter_column("ip", new_column_name="ip_hash")


def downgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as b:
            b.alter_column("ip_hash", new_column_name="ip")
