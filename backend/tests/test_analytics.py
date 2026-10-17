from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from mebot.analytics import cache, service
from mebot.models import Bot, Contact, OpenQuestion, UsageCounter
from tests.dash_helpers import bot_id, seed_session

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)  # a Saturday noon UTC
Q = [("user", "What is his tech stack?"), ("assistant", "Python and React.")]


def day(n: int, hour: int = 10) -> datetime:
    """`n` days before NOW's date, at `hour` UTC."""
    return datetime(2026, 10, 17, hour, tzinfo=UTC) - timedelta(days=n)


def set_tz(app, name):
    with app.state.session_factory() as db:
        db.get(Bot, bot_id(app)).timezone = name
        db.commit()


def run(app, range_key="7d", now=NOW) -> dict:
    with app.state.session_factory() as db:
        return service.overview(db, db.get(Bot, bot_id(app)), range_key, now)


def test_brand_new_bot_is_all_zeros(admin_client, app):
    o = run(app)
    k = o["kpis"]
    assert k["chats"] == {"value": 0, "previous": 0}
    assert k["unanswered_rate"] == {"value": None, "previous": None}
    assert k["avg_messages_per_chat"]["value"] is None
    assert o["top_questions"] == [] and o["sources"] == []
    assert len(o["series"]) == 7 and all(d["chats"] == 0 for d in o["series"])
    assert o["range"] == {"key": "7d", "from": "2026-10-11", "to": "2026-10-17", "timezone": "UTC"}


def test_kpis_and_previous_period(admin_client, app):
    seed_session(app, day(1), Q + Q, unanswered=True)  # 2 visitor msgs, 2 unanswered replies
    seed_session(app, day(2), Q, contact=True, owner_reply=True)
    seed_session(app, day(3), [])  # opened, never typed: not a chat
    seed_session(app, day(9), Q)  # previous period
    seed_session(app, day(10), Q + Q + Q)
    k = run(app)["kpis"]
    assert k["chats"] == {"value": 2, "previous": 2}
    assert k["visitor_messages"] == {"value": 3, "previous": 4}
    assert k["avg_messages_per_chat"] == {"value": 1.5, "previous": 2.0}
    # replies: 2 unanswered of 2 (session 1) + 1 normal (session 2); the owner's doesn't count
    assert k["unanswered_rate"]["value"] == pytest.approx(2 / 3, abs=1e-3)
    assert k["unanswered_rate"]["previous"] == 0
    assert k["contacts"] == {"value": 1, "previous": 0}
    assert k["owner_replies"] == {"value": 1, "previous": 0}


def test_open_questions_is_live_count(admin_client, app):
    with app.state.session_factory() as db:
        for status in ("open", "open", "answered"):
            db.add(
                OpenQuestion(
                    bot_id=bot_id(app), question="q", normalized="q" + status, status=status
                )
            )
        db.commit()
    assert run(app)["kpis"]["open_questions"] == {"value": 2, "previous": None}


def test_deleted_contacts_not_counted(admin_client, app):
    seed_session(app, day(1), Q, contact=True)
    with app.state.session_factory() as db:
        db.scalar(select(Contact)).deleted_at = NOW
        db.commit()
    assert run(app)["kpis"]["contacts"]["value"] == 0


def test_tokens_from_counters(admin_client, app):
    with app.state.session_factory() as db:
        for d, t, est in (("2026-10-16", 100, 0), ("2026-10-15", 50, 50), ("2026-09-01", 999, 0)):
            db.add(
                UsageCounter(
                    bot_id=bot_id(app),
                    scope="bot_day",
                    key="*",
                    window_start=d,
                    tokens=t,
                    estimated_tokens=est,
                )
            )
        db.commit()
    t = run(app)["kpis"]["tokens"]
    assert t["value"] == 150 and t["estimated"] is True


def test_series_buckets_per_local_day(admin_client, app):
    seed_session(app, day(0, 9), Q + Q)
    seed_session(app, day(0, 11), Q, unanswered=True)
    seed_session(app, day(6, 9), Q)
    s = run(app)["series"]
    assert s[-1] == {"date": "2026-10-17", "chats": 2, "visitor_messages": 3, "unanswered": 1}
    assert s[0]["date"] == "2026-10-11" and s[0]["chats"] == 1
    assert sum(d["chats"] for d in s) == 3


def test_series_uses_bot_timezone(admin_client, app):
    # 20:00 UTC on Oct 16 is 01:30 on Oct 17 in Kolkata.
    seed_session(app, datetime(2026, 10, 16, 20, tzinfo=UTC), Q)
    assert run(app)["series"][-2]["chats"] == 1
    set_tz(app, "Asia/Kolkata")
    o = run(app)
    assert o["range"]["timezone"] == "Asia/Kolkata"
    assert o["series"][-1]["chats"] == 1 and o["series"][-2]["chats"] == 0


def test_series_across_dst_change(admin_client, app):
    # New York leaves DST on 2026-11-01 (a 25-hour day). Local days stay distinct.
    set_tz(app, "America/New_York")
    now = datetime(2026, 11, 2, 15, tzinfo=UTC)
    seed_session(app, datetime(2026, 11, 1, 4, 30, tzinfo=UTC), Q)  # Nov 1 00:30 EDT
    seed_session(app, datetime(2026, 11, 1, 5, 30, tzinfo=UTC), Q)  # Nov 1 01:30 EDT
    seed_session(app, datetime(2026, 11, 1, 6, 30, tzinfo=UTC), Q)  # Nov 1 01:30 EST (repeat hour)
    seed_session(app, datetime(2026, 11, 2, 4, 59, tzinfo=UTC), Q)  # Nov 1 23:59 EST
    seed_session(app, datetime(2026, 11, 2, 5, 0, tzinfo=UTC), Q)  # Nov 2 00:00 EST
    seed_session(app, datetime(2026, 10, 31, 3, 59, tzinfo=UTC), Q)  # Oct 30 23:59 EDT
    s = {d["date"]: d["chats"] for d in run(app, now=now)["series"]}
    assert s["2026-11-01"] == 4 and s["2026-11-02"] == 1
    assert s["2026-10-31"] == 0 and s["2026-10-30"] == 1


def test_top_questions_group_and_exclude_personal(admin_client, app):
    for text in (
        "What is his tech stack?",
        "tech stack?",
        "What's his tech stack",
        "Does he know Kubernetes?",
        "Is he married?",
        "Is he married?",
    ):
        seed_session(app, day(1), [("user", text), ("assistant", "ok")])
    top = run(app)["top_questions"]
    assert top[0]["count"] == 3 and "tech stack" in top[0]["question"].lower()
    assert top[1] == {"question": "Does he know Kubernetes?", "count": 1}
    assert all("married" not in t["question"] for t in top)


def test_top_questions_limited_to_ten(admin_client, app):
    words = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima".split()
    for w in words:
        seed_session(app, day(1), [("user", f"Experience with {w}{w}?"), ("assistant", "ok")])
    assert len(run(app)["top_questions"]) == 10


def test_sources_by_origin_or_direct(admin_client, app):
    seed_session(app, day(1), Q, origin="https://shivansh.dev")
    seed_session(app, day(1), Q, origin="https://shivansh.dev")
    seed_session(app, day(2), Q, origin="https://other.example")
    seed_session(app, day(2), Q)
    seed_session(app, day(2), [], origin="https://empty.example")  # not a chat
    assert run(app)["sources"] == [
        {"origin": "https://shivansh.dev", "chats": 2},
        {"origin": "direct", "chats": 1},
        {"origin": "https://other.example", "chats": 1},
    ]


def test_status_block(admin_client, app):
    from tests.test_chat_limits import set_limits

    set_limits(app, paused=True, daily_message_cap=50)
    with app.state.session_factory() as db:
        db.add(
            UsageCounter(
                bot_id=bot_id(app),
                scope="bot_day",
                key="*",
                window_start="2026-10-17",
                messages=7,
                tokens=70,
            )
        )
        db.commit()
    st = run(app)["status"]
    assert st["paused"] is True
    assert st["today"] == {"messages": 7, "cap": 50, "tokens": 70, "token_cap": None}
    assert st["llm"]["configured"] is True and st["telegram"] == {"linked": False, "dead": 0}
    assert st["widget"]["origins"] == 0


def test_range_windows(admin_client, app):
    seed_session(app, day(20), Q)
    assert run(app, "7d")["kpis"]["chats"]["value"] == 0
    assert run(app, "30d")["kpis"]["chats"]["value"] == 1
    o = run(app, "90d")
    assert len(o["series"]) == 90 and o["range"]["from"] == "2026-07-20"


def test_cache_hit_and_invalidation(admin_client, app):
    clock = {"t": 1000.0}
    cache.clock = lambda: clock["t"]
    try:
        with app.state.session_factory() as db:
            bot = db.get(Bot, bot_id(app))
            first = service.cached_overview(db, bot, "7d")
            seed_session(app, datetime.now(UTC) - timedelta(hours=1), Q)
            assert service.cached_overview(db, bot, "7d") is first  # within 60 s
            clock["t"] += 61
            assert service.cached_overview(db, bot, "7d")["kpis"]["chats"]["value"] == 1
            cache.invalidate(bot.id)
            assert cache.get(bot.id, "7d", bot.timezone) is None
    finally:
        cache.clock = __import__("time").monotonic
