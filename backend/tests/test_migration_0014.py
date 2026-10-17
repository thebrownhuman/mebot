import sqlalchemy as sa
from alembic import command

from mebot.db import alembic_config, run_migrations
from tests.conftest import csrf
from tests.tg_helpers import link


def test_0014_copies_telegram_timezone_and_adds_columns(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    command.upgrade(alembic_config(url), "0013")
    eng = sa.create_engine(url)
    with eng.begin() as c:
        for bid in ("b1", "b2"):
            c.execute(
                sa.text(
                    "INSERT INTO bots (id, slug, name, created_at, updated_at,"
                    " registration_consent)"
                    " VALUES (:i, :i, 'n', '2026-01-01', '2026-01-01', 0)"
                ),
                {"i": bid},
            )
        c.execute(
            sa.text(
                "INSERT INTO telegram_configs (id, bot_id, enabled, mode, notify_new_session,"
                " notify_every_question, notify_unanswered, notify_contact, notify_limits,"
                " daily_digest, digest_hour, timezone, created_at, updated_at)"
                " VALUES ('t1','b1',1,'polling',1,0,1,1,1,1,21,'Asia/Kolkata',"
                "'2026-01-01','2026-01-01')"
            )
        )
    run_migrations(url)
    with eng.connect() as c:
        rows = dict(c.execute(sa.text("SELECT id, timezone FROM bots")).all())
        assert rows == {"b1": "Asia/Kolkata", "b2": "UTC"}
        # existing bots keep their data: retention starts as "forever"
        assert c.execute(sa.text("SELECT retention_days FROM bots")).scalars().all() == [None, None]
    insp = sa.inspect(eng)
    ix = {
        tuple(i["column_names"])
        for t in ("sessions", "messages", "access_log")
        for i in insp.get_indexes(t)
    }
    assert ("bot_id", "started_at") in ix
    assert ("bot_id", "created_at") in ix
    assert ("bot_id", "event", "created_at") in ix


def test_new_bot_defaults(admin_client, app):
    from mebot.repos import bots

    with app.state.session_factory() as db:
        bot = bots.get_primary(db)
        assert bot.timezone == "UTC" and bot.retention_days == 180


def test_telegram_timezone_patch_writes_bot(admin_client, app):
    from sqlalchemy import select

    from mebot.models import Bot, TelegramConfig

    link(app)
    r = admin_client.patch(
        "/api/admin/telegram", json={"timezone": "Asia/Kolkata"}, headers=csrf(admin_client)
    )
    assert r.status_code == 200, r.text
    assert r.json()["timezone"] == "Asia/Kolkata"
    with app.state.session_factory() as db:
        assert db.scalar(select(Bot.timezone)) == "Asia/Kolkata"
        assert db.scalar(select(TelegramConfig.timezone)) == "UTC"  # column left untouched
