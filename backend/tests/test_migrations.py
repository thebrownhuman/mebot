import sqlalchemy as sa

from mebot.db import run_migrations

NEW_TABLES = {"bots", "profiles", "sessions", "messages", "access_log"}


def test_upgrade_from_empty(tmp_path):
    url = f"sqlite:///{(tmp_path / 'e.db').as_posix()}"
    run_migrations(url)
    insp = sa.inspect(sa.create_engine(url))
    tables = set(insp.get_table_names())
    assert NEW_TABLES <= tables
    assert not any(t.startswith("legacy_") for t in tables)
    for t in NEW_TABLES - {"bots"}:
        cols = {c["name"] for c in insp.get_columns(t)}
        assert "bot_id" in cols
        assert any("bot_id" in ix["column_names"] for ix in insp.get_indexes(t)), t
    assert insp.get_foreign_keys("messages") == []
    msg_ix = [ix["column_names"] for ix in insp.get_indexes("messages")]
    assert ["session_id", "created_at"] in msg_ix
    # rerun is a no-op
    run_migrations(url)
