from datetime import UTC, datetime

from mebot.db import make_session_factory, run_migrations
from mebot.repos import bots, sessions


def test_messages_keep_insert_order_with_same_clock(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    run_migrations(url)
    fixed = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(sessions, "utcnow", lambda: fixed)
    with make_session_factory(url)() as db:
        bot = bots.create(db, slug="a", name="A")
        sid = sessions.create(db, bot.id, None)
        for i in range(20):
            sessions.add_message(db, bot.id, sid, "user", str(i))
        db.commit()
        assert [m.content for m in sessions.messages(db, bot.id, sid)] == [
            str(i) for i in range(20)
        ]
