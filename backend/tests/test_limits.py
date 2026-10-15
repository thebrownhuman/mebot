import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from mebot.db import make_session_factory, run_migrations
from mebot.limits import counters
from mebot.limits.memory import LoginLimiter, SlidingWindowLimiter
from mebot.limits.service import ChatLimiter, LimitExceeded
from mebot.models import BotLimits, UsageCounter

SECRET = "s3cret-key-for-tests"


class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


class WallClock:
    def __init__(self, dt: datetime):
        self.dt = dt

    def __call__(self) -> datetime:
        return self.dt


@pytest.fixture
def factory(tmp_path):
    url = f"sqlite:///{(tmp_path / 'lim.db').as_posix()}"
    run_migrations(url)
    return make_session_factory(url)


@pytest.fixture
def db(factory):
    with factory() as s:
        yield s


# --- in-memory sliding window --------------------------------------------------------


def test_sliding_window_math():
    clock = Clock()
    rl = SlidingWindowLimiter(limit=3, window_seconds=60, clock=clock)
    assert [rl.hit("a") for _ in range(3)] == [None, None, None]
    assert rl.hit("a") == 60  # oldest hit expires in 60s
    assert rl.hit("b") is None  # keys are independent
    clock.t += 30
    assert rl.hit("a") == 30
    clock.t += 30  # the first three hits leave the window
    assert rl.hit("a") is None


def test_sliding_window_per_call_limit_and_peek():
    clock = Clock()
    rl = SlidingWindowLimiter(limit=100, window_seconds=60, clock=clock)
    assert rl.hit("a", limit=1) is None
    assert rl.hit("a", limit=1) == 60
    assert rl.retry_after("a", limit=1) == 60  # peek does not record
    assert rl.retry_after("a", limit=5) is None
    rl.record("a")
    assert rl.retry_after("a", limit=2) == 60


def test_login_limiter_same_interface():
    clock = Clock()
    rl = LoginLimiter(clock=clock)
    for _ in range(5):
        assert rl.retry_after("1.2.3.4", "a@b.c") is None
        rl.record_failure("1.2.3.4", "a@b.c")
    assert rl.retry_after("1.2.3.4", "x@y.z") == 15 * 60
    assert rl.retry_after("9.9.9.9", "a@b.c") is None


# --- DB counters ---------------------------------------------------------------------


def test_ip_hash_is_hmac_and_raw_ip_never_stored(db):
    h = counters.ip_hash(SECRET, "203.0.113.7")
    assert len(h) == 64 and "203.0.113.7" not in h
    assert h == counters.ip_hash(SECRET, "203.0.113.7")
    assert h != counters.ip_hash("other", "203.0.113.7")
    day = datetime(2026, 10, 16, tzinfo=UTC).date()
    assert counters.consume(db, "b1", [("ip_day", h, 5)], day) is None
    db.commit()
    keys = [r.key for r in db.scalars(select(UsageCounter))]
    assert keys == [h]


def test_consume_counts_and_blocks_at_limit(db):
    day = datetime(2026, 10, 16, tzinfo=UTC).date()
    items = [("ip_day", "ip1", 2), ("bot_day", "*", 10)]
    assert counters.consume(db, "b1", items, day) is None
    assert counters.consume(db, "b1", items, day) is None
    assert counters.consume(db, "b1", items, day) == "ip_day"
    db.commit()
    # the failed attempt consumed nothing (all-or-nothing)
    assert counters.get(db, "b1", "bot_day", "*", day).messages == 2


def test_consume_is_all_or_nothing_on_later_scope(db):
    day = datetime(2026, 10, 16, tzinfo=UTC).date()
    assert counters.consume(db, "b1", [("bot_day", "*", 1)], day) is None
    assert counters.consume(db, "b1", [("ip_day", "ip1", 9), ("bot_day", "*", 1)], day) == "bot_day"
    db.commit()
    assert counters.get(db, "b1", "ip_day", "ip1", day).messages == 0


def test_day_rollover_resets(db):
    d1 = datetime(2026, 10, 16, tzinfo=UTC).date()
    d2 = d1 + timedelta(days=1)
    assert counters.consume(db, "b1", [("bot_day", "*", 1)], d1) is None
    assert counters.consume(db, "b1", [("bot_day", "*", 1)], d1) == "bot_day"
    assert counters.consume(db, "b1", [("bot_day", "*", 1)], d2) is None


def test_tokens_and_purge(db):
    old = datetime(2026, 10, 1, tzinfo=UTC)
    now = datetime(2026, 10, 16, 12, tzinfo=UTC)
    counters.add_tokens(db, "b1", [("bot_day", "*")], old.date(), 50, estimated=True, now=old)
    counters.add_tokens(db, "b1", [("bot_day", "*")], now.date(), 30, estimated=False, now=now)
    counters.add_tokens(db, "b1", [("bot_day", "*")], now.date(), 12, estimated=True, now=now)
    db.commit()
    row = counters.get(db, "b1", "bot_day", "*", now.date())
    assert (row.tokens, row.estimated_tokens, row.messages) == (42, 12, 0)
    assert counters.purge(db, now) == 1
    db.commit()
    assert counters.get(db, "b1", "bot_day", "*", old.date()) is None


def test_last_slot_race_exactly_one_wins(factory):
    day = datetime(2026, 10, 16, tzinfo=UTC).date()
    with factory() as s:
        for _ in range(4):
            assert counters.consume(s, "b1", [("bot_day", "*", 5)], day) is None
        s.commit()
    results: list[str | None] = []
    barrier = threading.Barrier(8)

    def worker():
        with factory() as s:
            barrier.wait()
            r = counters.consume(s, "b1", [("bot_day", "*", 5)], day)
            s.commit()
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(None) == 1 and results.count("bot_day") == 7
    with factory() as s:
        assert counters.get(s, "b1", "bot_day", "*", day).messages == 5


# --- chat limiter (enforcement order) --------------------------------------------------


def _limits(**over) -> BotLimits:
    lim = BotLimits(
        bot_id="b1",
        per_ip_per_minute=10,
        per_ip_per_day=100,
        per_session_messages=40,
        sessions_per_ip_per_hour=10,
        daily_message_cap=500,
        daily_token_cap=None,
        max_message_chars=1000,
        history_turns=12,
        paused=False,
        turnstile_enabled=False,
    )
    for k, v in over.items():
        setattr(lim, k, v)
    return lim


def _limiter(dt=datetime(2026, 10, 16, 23, 59, 30, tzinfo=UTC)):
    return ChatLimiter(SECRET, clock=Clock(), wall=WallClock(dt))


def _consume(lim, db, limits, ip="1.1.1.1", sid="s1"):
    lim.check_and_consume(db, "b1", limits, ip, sid)
    db.commit()


def test_scope_order_and_retry_after(db):
    lim = _limiter()
    limits = _limits(per_ip_per_minute=2, per_ip_per_day=3, per_session_messages=4)
    _consume(lim, db, limits)
    _consume(lim, db, limits)
    with pytest.raises(LimitExceeded) as ei:
        _consume(lim, db, limits)
    assert (ei.value.scope, ei.value.code, ei.value.retry_after) == (
        "ip_minute",
        "RATE_LIMITED",
        60,
    )
    lim.clock.t += 61
    _consume(lim, db, limits)
    with pytest.raises(LimitExceeded) as ei:
        _consume(lim, db, limits, sid="s2")
    # daily windows reopen at 00:00 UTC: 30s away on the frozen wall clock
    assert (ei.value.scope, ei.value.retry_after) == ("ip_day", 30)


def test_session_and_bot_caps(db):
    lim = _limiter()
    limits = _limits(per_session_messages=1, daily_message_cap=2)
    _consume(lim, db, limits, ip="a")
    with pytest.raises(LimitExceeded) as ei:
        _consume(lim, db, limits, ip="b")
    assert ei.value.scope == "session" and ei.value.retry_after is None
    _consume(lim, db, limits, ip="c", sid="s2")
    with pytest.raises(LimitExceeded) as ei:
        _consume(lim, db, limits, ip="d", sid="s3")
    assert (ei.value.scope, ei.value.code) == ("bot_day", "DAILY_CAP_REACHED")


def test_lowered_cap_blocks_immediately(db):
    lim = _limiter()
    for i in range(3):
        _consume(lim, db, _limits(), ip=f"ip{i}", sid=f"s{i}")
    with pytest.raises(LimitExceeded) as ei:
        _consume(lim, db, _limits(daily_message_cap=2), ip="new", sid="new")
    assert ei.value.scope == "bot_day"


def test_daily_token_cap(db):
    lim = _limiter()
    _consume(lim, db, _limits(daily_token_cap=100))
    lim.record_tokens(db, "b1", "1.1.1.1", 100, estimated=False)
    db.commit()
    with pytest.raises(LimitExceeded) as ei:
        _consume(lim, db, _limits(daily_token_cap=100), sid="s2")
    assert (ei.value.scope, ei.value.code) == ("bot_tokens", "DAILY_CAP_REACHED")
    # the refused request consumed no daily message
    assert counters.get(db, "b1", "bot_day", "*", lim.today()).messages == 1


def test_rate_limited_log_once_per_minute():
    lim = _limiter()
    assert lim.should_log("ip_minute", "k") is True
    assert lim.should_log("ip_minute", "k") is False
    assert lim.should_log("ip_day", "k") is True
    lim.clock.t += 61
    assert lim.should_log("ip_minute", "k") is True


def test_session_creation_limit():
    lim = _limiter()
    limits = _limits(sessions_per_ip_per_hour=2)
    assert lim.session_start_wait(limits, "1.1.1.1") is None
    assert lim.session_start_wait(limits, "1.1.1.1") is None
    assert lim.session_start_wait(limits, "1.1.1.1") == 3600
