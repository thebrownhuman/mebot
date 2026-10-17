import sqlite3

import sqlalchemy as sa

from mebot.db import run_migrations
from mebot.legacy import import_legacy
from mebot.limits.counters import ip_hash

LEGACY_SCHEMA = """
CREATE TABLE profile (id INTEGER PRIMARY KEY CHECK (id = 1), content TEXT NOT NULL,
                      updated_at REAL NOT NULL);
CREATE TABLE sessions (id TEXT PRIMARY KEY, recruiter_name TEXT, started_at REAL NOT NULL);
CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                       role TEXT NOT NULL, content TEXT NOT NULL, ts REAL NOT NULL,
                       FOREIGN KEY (session_id) REFERENCES sessions(id));
CREATE TABLE access_log (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
                         event TEXT NOT NULL, detail TEXT, ip TEXT, ts REAL NOT NULL);
"""


def make_legacy_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    conn.execute("INSERT INTO profile VALUES (1, 'NAME: Legacy Person', 1700000000.5)")
    conn.execute("INSERT INTO sessions VALUES ('s1', 'Alice', 1760000000.0)")
    conn.execute("INSERT INTO sessions VALUES ('s2', NULL, 1760000100.0)")
    conn.executemany(
        "INSERT INTO messages (session_id, role, content, ts) VALUES (?,?,?,?)",
        [("s1", "user", "hi", 1760000001.0), ("s1", "assistant", "hello", 1760000002.0)],
    )
    conn.execute(
        "INSERT INTO access_log (session_id, event, detail, ip, ts) "
        "VALUES ('s1', 'session_start', 'Alice', '127.0.0.1', 1760000000.0)"
    )
    conn.commit()
    conn.close()


def counts(engine):
    with engine.connect() as c:
        return {
            t: c.execute(sa.text(f"SELECT COUNT(*) FROM {t}")).scalar_one()
            for t in ("bots", "profile_notes", "sessions", "messages", "access_log")
        }


def test_legacy_db_is_imported_under_default_bot(tmp_path):
    path = tmp_path / "old.db"
    make_legacy_db(path)
    url = f"sqlite:///{path.as_posix()}"
    run_migrations(url)
    engine = sa.create_engine(url)
    tables = set(sa.inspect(engine).get_table_names())
    assert {"legacy_profile", "legacy_sessions", "legacy_messages", "legacy_access_log"} <= tables
    assert counts(engine) == {
        "bots": 1,
        "profile_notes": 1,
        "sessions": 2,
        "messages": 2,
        "access_log": 1,
    }
    with engine.connect() as c:
        bot = c.execute(sa.text("SELECT id, slug FROM bots")).one()
        assert bot.slug == "default"
        for t in ("profile_notes", "sessions", "messages", "access_log"):
            ids = c.execute(sa.text(f"SELECT DISTINCT bot_id FROM {t}")).scalars().all()
            assert ids == [bot.id]
        content = c.execute(sa.text("SELECT content FROM profile_notes")).scalar_one()
        assert content == "NAME: Legacy Person"
        s1 = c.execute(
            sa.text("SELECT recruiter_name, started_at FROM sessions WHERE id='s1'")
        ).one()
        assert s1.recruiter_name == "Alice"
        # 1760000000 epoch == 2025-10-09 08:53:20 UTC
        assert str(s1.started_at).startswith("2025-10-09 08:53:20")


def test_import_is_idempotent(tmp_path):
    path = tmp_path / "old.db"
    make_legacy_db(path)
    url = f"sqlite:///{path.as_posix()}"
    run_migrations(url)
    engine = sa.create_engine(url)
    before = counts(engine)
    with engine.begin() as c:
        import_legacy(c)
        import_legacy(c)
    run_migrations(url)
    assert counts(engine) == before


def test_imported_data_served_by_api(tmp_path):
    from fastapi.testclient import TestClient

    from mebot.config import Settings
    from mebot.main import create_app
    from tests.conftest import do_setup

    path = tmp_path / "old.db"
    make_legacy_db(path)
    s = Settings(_env_file=None, data_dir=tmp_path, database_url=f"sqlite:///{path.as_posix()}")
    with TestClient(create_app(s)) as c:
        assert do_setup(c).status_code == 201
        assert c.get("/api/admin/profile/notes").json() == {"content": "NAME: Legacy Person"}
        sessions = c.get("/api/admin/sessions").json()
        assert [x["id"] for x in sessions] == ["s2", "s1"]
        assert sessions[1] == {
            "id": "s1",
            "recruiter_name": "Alice",
            "started_at": 1760000000.0,
            "turns": 2,
        }
        msgs = c.get("/api/admin/sessions/s1/messages").json()
        assert msgs == [
            {"role": "user", "content": "hi", "ts": 1760000001.0},
            {"role": "assistant", "content": "hello", "ts": 1760000002.0},
        ]
        log = c.get("/api/admin/log").json()
        assert log == [
            {
                "event": "session_start",
                "detail": "Alice",
                "ip_hash": ip_hash(c.app.state.secret_key, "127.0.0.1")[:12],
                "ts": 1760000000.0,
            }
        ]
