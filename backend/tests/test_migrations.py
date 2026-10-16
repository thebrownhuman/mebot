import sqlalchemy as sa
from alembic import command

from mebot.db import alembic_config, run_migrations

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


def test_0008_telegram_tables(tmp_path):
    url = f"sqlite:///{(tmp_path / 't.db').as_posix()}"
    run_migrations(url)
    insp = sa.inspect(sa.create_engine(url))
    tg = {c["name"]: c for c in insp.get_columns("telegram_configs")}
    assert set(tg) >= {
        "id",
        "bot_id",
        "bot_token_encrypted",
        "bot_token_last4",
        "bot_username",
        "chat_id",
        "link_code_hash",
        "link_code_expires_at",
        "enabled",
        "mode",
        "webhook_secret",
        "last_update_id",
        "notify_new_session",
        "notify_every_question",
        "notify_unanswered",
        "notify_contact",
        "notify_limits",
        "daily_digest",
        "digest_hour",
        "timezone",
        "last_digest_date",
        "lease_owner",
        "lease_expires_at",
        "error",
        "created_at",
        "updated_at",
    }
    assert tg["chat_id"]["nullable"] is True
    assert any(
        ix["unique"] and ix["column_names"] == ["bot_id"]
        for ix in insp.get_indexes("telegram_configs")
    )
    out = {c["name"] for c in insp.get_columns("notifications")}
    assert out >= {
        "id",
        "bot_id",
        "kind",
        "payload",
        "status",
        "attempts",
        "next_attempt_at",
        "telegram_message_id",
        "session_id",
        "ref_message_id",
        "last_error",
        "created_at",
        "updated_at",
    }
    assert ["status", "next_attempt_at"] in [
        ix["column_names"] for ix in insp.get_indexes("notifications")
    ]
    contacts = {c["name"] for c in insp.get_columns("contacts")}
    assert contacts >= {
        "id",
        "bot_id",
        "session_id",
        "name",
        "email",
        "company",
        "role",
        "note",
        "created_at",
        "deleted_at",
    }
    msg = {c["name"]: c for c in insp.get_columns("messages")}
    assert msg["from_owner"]["nullable"] is False
    for t in ("telegram_configs", "notifications", "contacts"):
        assert insp.get_foreign_keys(t) == []


def test_0009_identity_persona_columns(tmp_path):
    url = f"sqlite:///{(tmp_path / 't.db').as_posix()}"
    run_migrations(url)
    insp = sa.inspect(sa.create_engine(url))
    cols = {c["name"]: c for c in insp.get_columns("profile_identity")}
    assert cols["pronouns"]["nullable"] is False
    assert "they/them" in str(cols["pronouns"]["default"])
    assert cols["assistant_greeting"]["nullable"] is True


def test_0009_learning_tables(tmp_path):
    url = f"sqlite:///{(tmp_path / 't.db').as_posix()}"
    run_migrations(url)
    insp = sa.inspect(sa.create_engine(url))
    oq = {c["name"]: c for c in insp.get_columns("open_questions")}
    assert set(oq) >= {
        "id", "bot_id", "question", "normalized", "ask_count", "first_asked_at",
        "last_asked_at", "last_session_id", "status", "answered_fact_id",
        "last_notified_at", "created_at", "updated_at",
    }  # fmt: skip
    assert oq["ask_count"]["nullable"] is False
    lf = {c["name"]: c for c in insp.get_columns("learned_facts")}
    assert set(lf) >= {
        "id", "bot_id", "open_question_id", "question", "answer_raw", "fact_text",
        "suggested_section", "suggested_field", "suggested_value", "status", "source",
        "needs_review", "approved_at", "created_at", "updated_at", "deleted_at",
    }  # fmt: skip
    assert lf["deleted_at"]["nullable"] is True
    assert ["bot_id", "status"] in [i["column_names"] for i in insp.get_indexes("open_questions")]
    for t in ("open_questions", "learned_facts"):
        assert insp.get_foreign_keys(t) == []


def _seed_0009(url):
    command.upgrade(alembic_config(url), "0009")
    eng = sa.create_engine(url)
    ts = "'2026-01-01 00:00:00'"
    with eng.begin() as c:
        c.execute(
            sa.text(
                "INSERT INTO bots (id, slug, name, created_at, updated_at, registration_consent) "
                f"VALUES ('b1', 'jane', 'Jane', {ts}, {ts}, 0)"
            )
        )
        for i, (label, u) in enumerate(
            [
                ("LinkedIn", "https://www.linkedin.com/in/jane"),
                ("Code", "https://github.com/jane"),
                ("Insta", "https://instagram.com/jane"),
                ("Site", "https://jane.dev"),
            ]
        ):
            c.execute(
                sa.text(
                    "INSERT INTO profile_links (id, bot_id, sort_order, label, url, created_at, "
                    f"updated_at) VALUES ('l{i}', 'b1', {i}, '{label}', '{u}', {ts}, {ts})"
                )
            )
        c.execute(
            sa.text(
                "INSERT INTO profile_identity (id, bot_id, full_name, headline, location, "
                "open_to, summary, email_public, phone_public, count_internships, "
                f"count_freelance, created_at, updated_at) VALUES ('i1', 'b1', 'Jane', '', '', "
                f"'', '', 'jane@example.com', '+91 98765 43210', 0, 1, {ts}, {ts})"
            )
        )
    return eng


def test_0010_maps_links_email_and_phone(tmp_path):
    url = f"sqlite:///{(tmp_path / 't.db').as_posix()}"
    eng = _seed_0009(url)
    command.upgrade(alembic_config(url), "0010")
    with eng.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT kind, value, label, share, sort_order FROM profile_links "
                "WHERE deleted_at IS NULL ORDER BY sort_order"
            )
        ).all()
    assert [(r.kind, r.share) for r in rows] == [
        ("linkedin", 1), ("github", 1), ("instagram", 1), ("website", 1),
        ("email", 1), ("phone", 0),
    ]  # fmt: skip
    assert rows[0].value == "https://www.linkedin.com/in/jane"
    assert (rows[4].value, rows[4].label) == ("jane@example.com", "Email")
    assert rows[5].value == "+91 98765 43210"
    cols = {c["name"] for c in sa.inspect(eng).get_columns("profile_links")}
    assert "url" not in cols and {"kind", "value", "share"} <= cols
    # Old identity columns stay (documented as unused).
    icols = {c["name"] for c in sa.inspect(eng).get_columns("profile_identity")}
    assert {"email_public", "phone_public"} <= icols


def test_0010_idempotent_and_skips_existing_channels(tmp_path):
    url = f"sqlite:///{(tmp_path / 't.db').as_posix()}"
    eng = _seed_0009(url)
    cfg = alembic_config(url)
    command.upgrade(cfg, "0010")
    command.downgrade(cfg, "0009")
    command.upgrade(cfg, "0010")
    with eng.connect() as c:
        n = c.execute(sa.text("SELECT count(*) FROM profile_links")).scalar()
        kinds = [r[0] for r in c.execute(sa.text("SELECT kind FROM profile_links"))]
    assert n == 6 and kinds.count("phone") == 1 and kinds.count("email") == 1


def test_0011_widget_settings(tmp_path):
    url = f"sqlite:///{(tmp_path / 'w.db').as_posix()}"
    run_migrations(url)
    insp = sa.inspect(sa.create_engine(url))
    cols = {c["name"] for c in insp.get_columns("widget_settings")}
    assert cols >= {
        "id", "bot_id", "enabled", "allowed_origins", "allow_any_origin", "primary_color",
        "theme", "position", "title", "avatar_url", "launcher_label", "suggested_questions",
        "show_orb", "auto_open_seconds", "created_at", "updated_at",
    }  # fmt: skip
    ix = {i["name"]: i for i in insp.get_indexes("widget_settings")}
    assert ix["ux_widget_settings_bot_id"]["unique"]
    command.downgrade(alembic_config(url), "0010")
    assert "widget_settings" not in sa.inspect(sa.create_engine(url)).get_table_names()


def test_0012_import_jobs(tmp_path):
    url = f"sqlite:///{(tmp_path / 'i.db').as_posix()}"
    run_migrations(url)
    insp = sa.inspect(sa.create_engine(url))
    cols = {c["name"] for c in insp.get_columns("import_jobs")}
    assert cols >= {
        "id", "bot_id", "kind", "status", "filename", "sha256", "size_bytes", "draft",
        "source_text", "error_code", "error_message", "applied_summary", "created_at",
        "updated_at", "expires_at",
    }  # fmt: skip
    command.downgrade(alembic_config(url), "0011")
    assert "import_jobs" not in sa.inspect(sa.create_engine(url)).get_table_names()
