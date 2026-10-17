from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from mebot import retention
from mebot.models import AccessLog, Bot, Notification, UsageCounter, new_id
from tests.dash_helpers import bot_id, counts, seed_session

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)
CHAT = [("user", "hi"), ("assistant", "hello")]


def _seed(app):
    old = seed_session(app, NOW - timedelta(days=200), CHAT, contact=True)
    mid = seed_session(app, NOW - timedelta(days=100), CHAT)
    new = seed_session(app, NOW - timedelta(days=2), CHAT, contact=True)
    return old, mid, new


def _set_days(app, days):
    with app.state.session_factory() as db:
        db.get(Bot, bot_id(app)).retention_days = days
        db.commit()


def test_purge_deletes_only_older_than_window(admin_client, app):
    old, mid, new = _seed(app)
    with app.state.session_factory() as db:
        res = retention.purge_bot(db, bot_id(app), 180, NOW)
        db.commit()
    assert res["sessions"] == 1 and res["messages"] == 2 and res["contacts"] == 1
    c = counts(app)
    assert c["sessions"] == 2 and c["messages"] == 4 and c["contacts"] == 1
    with app.state.session_factory() as db:
        linked = set(
            db.scalars(select(AccessLog.session_id).where(AccessLog.session_id.is_not(None)))
        )
    assert old not in linked and new in linked


def test_purge_logs_counts_only(admin_client, app):
    _seed(app)
    with app.state.session_factory() as db:
        retention.purge_bot(db, bot_id(app), 180, NOW)
        db.commit()
        row = db.scalar(select(AccessLog).where(AccessLog.event == "RETENTION_PURGED"))
    assert row is not None and row.session_id is None
    assert row.detail == "sessions=1 messages=2 contacts=1"


def test_nothing_to_purge_logs_nothing(admin_client, app):
    seed_session(app, NOW - timedelta(days=1), CHAT)
    with app.state.session_factory() as db:
        assert retention.purge_bot(db, bot_id(app), 180, NOW)["sessions"] == 0
        db.commit()
        assert db.scalar(select(AccessLog).where(AccessLog.event == "RETENTION_PURGED")) is None


def test_null_retention_keeps_everything(admin_client, app):
    _seed(app)
    _set_days(app, None)
    before = counts(app)
    assert retention.purge_all_bots(app.state.session_factory, NOW) == 0
    assert counts(app) == before


def test_purge_all_bots_uses_each_window(admin_client, app):
    _seed(app)
    _set_days(app, 30)
    assert retention.purge_all_bots(app.state.session_factory, NOW) == 2
    assert counts(app)["sessions"] == 1


def test_counters_and_outbox_untouched(admin_client, app):
    bid = bot_id(app)
    seed_session(app, NOW - timedelta(days=400), CHAT)
    with app.state.session_factory() as db:
        db.add(
            UsageCounter(bot_id=bid, scope="bot", key="-", window_start="2020-01-01", messages=3)
        )
        db.add(Notification(bot_id=bid, kind="x", payload="{}", status="sent"))
        db.commit()
        retention.purge_bot(db, bid, 30, NOW)
        db.commit()
        assert db.scalar(select(UsageCounter.id)) is not None
        assert db.scalar(select(Notification.id)) is not None


def test_delete_all_and_preview(admin_client, app):
    _seed(app)
    with app.state.session_factory() as db:
        assert retention.preview(db, bot_id(app), 30, NOW) == 2
        assert retention.preview(db, bot_id(app), None, NOW) == 0
        assert retention.delete_all(db, bot_id(app)) == 3
        db.commit()
    c = counts(app)
    assert c["sessions"] == c["messages"] == c["contacts"] == 0


def test_other_bots_untouched(admin_client, app):
    _seed(app)
    with app.state.session_factory() as db:
        other = new_id()
        retention.purge_bot(db, other, 1, NOW)
        retention.delete_all(db, other)
        db.commit()
    assert counts(app)["sessions"] == 3


def test_startup_purge(settings):
    from fastapi.testclient import TestClient

    from mebot.main import create_app
    from tests.conftest import do_setup

    app = create_app(settings)
    with TestClient(app) as c:
        assert do_setup(c).status_code == 201
        seed_session(app, datetime.now(UTC) - timedelta(days=400), CHAT)
        assert counts(app)["sessions"] == 1
    with TestClient(create_app(settings)):  # the next boot purges
        pass
    assert counts(app)["sessions"] == 0
