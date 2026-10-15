from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from mebot.models import AccessLog, BotLimits, LLMConfig, UsageCounter
from tests.conftest import csrf, do_setup, setup_body


def set_limits(app, **over):
    from mebot.repos import bots
    from mebot.repos import limits as limits_repo

    with app.state.session_factory() as db:
        row = limits_repo.get_or_create(db, bots.get_primary(db).id)
        for k, v in over.items():
            setattr(row, k, v)
        db.commit()


def new_session(c) -> str:
    r = c.post("/api/session", json={})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def chat(c, sid, message="hi"):
    return c.post("/api/chat", json={"session_id": sid, "message": message})


def events(app, name):
    with app.state.session_factory() as db:
        return list(db.scalars(select(AccessLog).where(AccessLog.event == name)))


def test_limits_row_created_with_defaults(admin_client, app):
    new_session(admin_client)
    with app.state.session_factory() as db:
        row = db.scalar(select(BotLimits))
    assert (row.per_ip_per_minute, row.daily_message_cap, row.max_message_chars) == (10, 500, 1000)
    assert row.daily_token_cap is None and row.paused is False


def test_ip_minute_429_shape_and_retry_after(admin_client, app, fake_llm):
    set_limits(app, per_ip_per_minute=2)
    sid = new_session(admin_client)
    assert chat(admin_client, sid).status_code == 200
    assert chat(admin_client, sid).status_code == 200
    r = chat(admin_client, sid)
    assert r.status_code == 429
    assert r.json() == {
        "error": {
            "code": "RATE_LIMITED",
            "message": "You're sending messages quickly — please wait a minute.",
            "status": 429,
            "details": [{"field": "scope", "message": "ip_minute"}],
        }
    }
    assert 1 <= int(r.headers["retry-after"]) <= 60
    assert len(fake_llm.streams) == 2
    chat(admin_client, sid)  # second refusal within the minute: not logged again
    assert len(events(app, "RATE_LIMITED")) == 1


@pytest.mark.parametrize(
    ("over", "scope", "code"),
    [
        ({"per_ip_per_day": 1}, "ip_day", "RATE_LIMITED"),
        ({"per_session_messages": 1}, "session", "RATE_LIMITED"),
        ({"daily_message_cap": 1}, "bot_day", "DAILY_CAP_REACHED"),
    ],
)
def test_each_daily_scope(admin_client, app, over, scope, code):
    set_limits(app, **over)
    sid = new_session(admin_client)
    assert chat(admin_client, sid).status_code == 200
    r = chat(admin_client, sid)
    assert r.status_code == 429
    err = r.json()["error"]
    assert err["code"] == code and err["details"] == [{"field": "scope", "message": scope}]
    if scope == "session":
        assert "retry-after" not in r.headers
    else:
        assert 1 <= int(r.headers["retry-after"]) <= 86400


def test_check_order_ip_day_before_session(admin_client, app):
    set_limits(app, per_ip_per_day=1, per_session_messages=1, daily_message_cap=1)
    sid = new_session(admin_client)
    chat(admin_client, sid)
    assert chat(admin_client, sid).json()["error"]["details"][0]["message"] == "ip_day"


def test_paused_503_no_llm_no_counters(admin_client, app, fake_llm):
    sid = new_session(admin_client)
    set_limits(app, paused=True, paused_message="Back on Monday!")
    r = chat(admin_client, sid)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "BOT_PAUSED"
    assert r.json()["error"]["message"] == "Back on Monday!"
    set_limits(app, paused_message=None)
    assert "paused" in chat(admin_client, sid).json()["error"]["message"].lower()
    assert fake_llm.streams == []
    with app.state.session_factory() as db:
        assert db.scalars(select(UsageCounter)).all() == []


def test_paused_checked_before_llm_config(admin_client, app):
    sid = new_session(admin_client)
    with app.state.session_factory() as db:
        db.query(LLMConfig).delete()
        db.commit()
    set_limits(app, paused=True)
    assert chat(admin_client, sid).json()["error"]["code"] == "BOT_PAUSED"


def test_message_length_boundary(admin_client, app):
    set_limits(app, max_message_chars=100)
    sid = new_session(admin_client)
    assert chat(admin_client, sid, "x" * 100).status_code == 200
    r = chat(admin_client, sid, "x" * 101)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "MESSAGE_TOO_LONG"
    assert err["details"] == [{"field": "message", "message": "max 100 characters"}]


def test_length_checked_before_rate_limits(admin_client, app, fake_llm):
    set_limits(app, per_ip_per_minute=1, max_message_chars=100)
    sid = new_session(admin_client)
    for _ in range(3):
        assert chat(admin_client, sid, "x" * 101).status_code == 422
    assert chat(admin_client, sid).status_code == 200


def test_day_rollover_resets_counts(admin_client, app):
    set_limits(app, per_ip_per_day=1)
    lim = app.state.chat_limiter
    lim.wall = lambda: datetime(2026, 10, 16, 23, 59, tzinfo=UTC)
    sid = new_session(admin_client)
    assert chat(admin_client, sid).status_code == 200
    r = chat(admin_client, sid)
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    lim.wall = lambda: datetime(2026, 10, 17, 0, 0, 1, tzinfo=UTC)
    assert chat(admin_client, sid).status_code == 200


def test_ip_never_stored_raw_in_counters(admin_client, app):
    sid = new_session(admin_client)
    chat(admin_client, sid)
    with app.state.session_factory() as db:
        keys = {r.key for r in db.scalars(select(UsageCounter))}
    assert "testclient" not in keys and "*" in keys and sid in keys


def test_session_creation_limit(admin_client, app):
    set_limits(app, sessions_per_ip_per_hour=2)
    new_session(admin_client)
    new_session(admin_client)
    r = admin_client.post("/api/session", json={})
    assert r.status_code == 429
    err = r.json()["error"]
    assert err["code"] == "RATE_LIMITED" and err["details"][0]["message"] == "session_start"
    assert int(r.headers["retry-after"]) > 0


# --- setup / probes ------------------------------------------------------------------


def test_setup_token_brute_force_429_after_10(app, client, monkeypatch):
    app.state.settings.setup_token = "the-real-token"
    h = csrf(client)
    for _ in range(10):
        r = client.post("/api/setup", json=setup_body(setup_token="guess"), headers=h)
        assert r.status_code == 403
    r = client.post("/api/setup", json=setup_body(setup_token="the-real-token"), headers=h)
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    # the probe endpoints share the same budget
    probe = client.post("/api/setup/llm-test", json={**setup_body()["llm"]}, headers=h)
    assert probe.status_code == 429


def test_probe_calls_count_toward_setup_limit(app, client):
    h = csrf(client)
    for _ in range(10):
        assert (
            client.post("/api/setup/llm-models", json=setup_body()["llm"], headers=h).status_code
            == 200
        )
    assert (
        client.post("/api/setup/llm-models", json=setup_body()["llm"], headers=h).status_code == 429
    )


def test_successful_setup_not_blocked_by_own_attempts(client):
    assert do_setup(client).status_code == 201
