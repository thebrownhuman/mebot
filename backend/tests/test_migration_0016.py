import re
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import command

from mebot.db import alembic_config, run_migrations
from mebot.limits.counters import ip_hash

KEY = "test-secret-key"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _seed(url: str, n: int) -> None:
    command.upgrade(alembic_config(url), "0015")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    eng = sa.create_engine(url)
    with eng.begin() as c:
        c.execute(
            sa.text(
                "INSERT INTO access_log (id, bot_id, event, ip, created_at) "
                "VALUES (:id, 'b', 'question', :ip, :ts)"
            ),
            [{"id": f"a{i}", "ip": f"10.0.{i // 256}.{i % 256}", "ts": now} for i in range(n)]
            + [{"id": "anull", "ip": None, "ts": now}],
        )
        c.execute(
            sa.text(
                "INSERT INTO admin_sessions (id, admin_id, created_at, expires_at, "
                "last_seen_at, ip) VALUES ('s1', 'adm', :ts, :ts, :ts, '192.168.1.9')"
            ),
            {"ts": now},
        )
    eng.dispose()


def test_0016_hashes_raw_ips_in_place(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    _seed(url, 2500)  # > one 1k batch
    run_migrations(url, secret_key=KEY)
    eng = sa.create_engine(url)
    insp = sa.inspect(eng)
    assert "ip" not in {c["name"] for c in insp.get_columns("access_log")}
    assert "ip" not in {c["name"] for c in insp.get_columns("admin_sessions")}
    with eng.connect() as c:
        got = dict(c.execute(sa.text("SELECT id, ip_hash FROM access_log")).all())
        sess = c.execute(sa.text("SELECT ip_hash FROM admin_sessions")).scalar_one()
    assert got["a0"] == ip_hash(KEY, "10.0.0.0")
    assert got["a2499"] == ip_hash(KEY, "10.0.9.195")
    assert got["anull"] is None
    assert sess == ip_hash(KEY, "192.168.1.9")
    run_migrations(url, secret_key=KEY)  # re-running is a no-op


def test_no_raw_ip_left_anywhere(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    _seed(url, 5)
    run_migrations(url, secret_key=KEY)
    eng = sa.create_engine(url)
    ipv4 = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
    with eng.connect() as c:
        for table in sa.inspect(eng).get_table_names():
            for row in c.execute(sa.text(f'SELECT * FROM "{table}"')):
                for v in row:
                    assert not (isinstance(v, str) and ipv4.search(v)), (table, v)


def test_rehash_skips_values_already_hashed(tmp_path):
    from mebot.limits.counters import hash_ip_value

    h = ip_hash(KEY, "1.2.3.4")
    assert hash_ip_value(KEY, h) == h
    assert HEX64.match(hash_ip_value(KEY, "1.2.3.4"))
    assert hash_ip_value(KEY, None) is None
