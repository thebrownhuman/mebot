import sqlalchemy as sa

from mebot.db import run_migrations

NEW_TABLES = {"bots", "profile_notes", "sessions", "messages", "access_log"}


def test_upgrade_from_empty(tmp_path):
    url = f"sqlite:///{(tmp_path / 'e.db').as_posix()}"
    run_migrations(url)
    insp = sa.inspect(sa.create_engine(url))
    tables = set(insp.get_table_names())
    assert NEW_TABLES <= tables
    # 0005 keeps the (empty, on a fresh db) blob table as legacy_profiles.
    assert {t for t in tables if t.startswith("legacy_")} == {"legacy_profiles"}
    for t in NEW_TABLES - {"bots"}:
        cols = {c["name"] for c in insp.get_columns(t)}
        assert "bot_id" in cols
        assert any("bot_id" in ix["column_names"] for ix in insp.get_indexes(t)), t
    assert insp.get_foreign_keys("messages") == []
    msg_ix = [ix["column_names"] for ix in insp.get_indexes("messages")]
    assert ["session_id", "created_at"] in msg_ix
    # rerun is a no-op
    run_migrations(url)


def test_0003_auth_tables(tmp_path):
    url = f"sqlite:///{(tmp_path / 'a.db').as_posix()}"
    run_migrations(url)
    insp = sa.inspect(sa.create_engine(url))
    tables = set(insp.get_table_names())
    assert {"admins", "admin_sessions"} <= tables
    admin_cols = {c["name"]: c for c in insp.get_columns("admins")}
    assert set(admin_cols) >= {
        "id",
        "email",
        "password_hash",
        "bot_id",
        "created_at",
        "updated_at",
        "deleted_at",
    }
    assert admin_cols["bot_id"]["nullable"] is True
    assert any(
        ix["unique"] and ix["column_names"] == ["email"] for ix in insp.get_indexes("admins")
    )
    sess_cols = {c["name"] for c in insp.get_columns("admin_sessions")}
    assert sess_cols >= {
        "id",
        "admin_id",
        "created_at",
        "expires_at",
        "last_seen_at",
        "ip",
        "user_agent",
    }
    sess_ix = [ix["column_names"] for ix in insp.get_indexes("admin_sessions")]
    assert ["admin_id"] in sess_ix and ["expires_at"] in sess_ix
    bot_cols = {c["name"]: c for c in insp.get_columns("bots")}
    assert bot_cols["registration_consent"]["nullable"] is False
    assert bot_cols["setup_completed_at"]["nullable"] is True
    for t in ("admins", "admin_sessions"):
        assert insp.get_foreign_keys(t) == []


def test_0003_keeps_existing_bot_rows(tmp_path):
    from alembic import command

    from mebot.db import alembic_config

    url = f"sqlite:///{(tmp_path / 'b.db').as_posix()}"
    command.upgrade(alembic_config(url), "0002")
    eng = sa.create_engine(url)
    with eng.begin() as c:
        c.execute(
            sa.text(
                "INSERT INTO bots (id, slug, name, created_at, updated_at) "
                "VALUES ('b1', 'default', 'Default', '2026-01-01', '2026-01-01')"
            )
        )
    run_migrations(url)
    with eng.connect() as c:
        row = c.execute(sa.text("SELECT registration_consent, setup_completed_at FROM bots")).one()
    assert not row.registration_consent and row.setup_completed_at is None


def test_0007_limits_and_counters(tmp_path):
    url = f"sqlite:///{(tmp_path / 'l.db').as_posix()}"
    run_migrations(url)
    insp = sa.inspect(sa.create_engine(url))
    lim = {c["name"]: c for c in insp.get_columns("bot_limits")}
    assert set(lim) >= {
        "id",
        "bot_id",
        "per_ip_per_minute",
        "per_ip_per_day",
        "per_session_messages",
        "sessions_per_ip_per_hour",
        "daily_message_cap",
        "daily_token_cap",
        "max_message_chars",
        "history_turns",
        "paused",
        "paused_message",
        "turnstile_enabled",
        "created_at",
        "updated_at",
    }
    assert lim["daily_token_cap"]["nullable"] is True
    assert any(
        ix["unique"] and ix["column_names"] == ["bot_id"] for ix in insp.get_indexes("bot_limits")
    )
    cnt = {c["name"] for c in insp.get_columns("usage_counters")}
    assert cnt >= {
        "id",
        "bot_id",
        "scope",
        "key",
        "window_start",
        "messages",
        "tokens",
        "estimated_tokens",
        "created_at",
        "updated_at",
    }
    assert any(
        ix["unique"] and ix["column_names"] == ["bot_id", "scope", "key", "window_start"]
        for ix in insp.get_indexes("usage_counters")
    )
    for t in ("bot_limits", "usage_counters"):
        assert insp.get_foreign_keys(t) == []
