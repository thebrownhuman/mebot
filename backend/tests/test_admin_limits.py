from datetime import timedelta

import pytest

from mebot.llm.base import Usage
from tests.conftest import csrf
from tests.test_chat_limits import chat, new_session, set_limits

FIELDS = {
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
    "turnstile_available",
}


def test_get_defaults(admin_client):
    body = admin_client.get("/api/admin/limits").json()
    assert set(body) == FIELDS
    assert body["per_ip_per_minute"] == 10 and body["daily_message_cap"] == 500
    assert body["turnstile_available"] is False


def test_put_updates_and_partial(admin_client):
    r = admin_client.put(
        "/api/admin/limits",
        json={
            "per_ip_per_minute": 5,
            "daily_token_cap": 200000,
            "paused": True,
            "paused_message": "Back soon",
        },
        headers=csrf(admin_client),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["per_ip_per_minute"] == 5 and body["daily_token_cap"] == 200000
    assert body["paused"] is True and body["daily_message_cap"] == 500
    r = admin_client.put(
        "/api/admin/limits", json={"daily_token_cap": None}, headers=csrf(admin_client)
    )
    assert r.json()["daily_token_cap"] is None and r.json()["per_ip_per_minute"] == 5
    assert admin_client.get("/api/public/config").json()["paused"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("per_ip_per_minute", 0),
        ("per_ip_per_minute", 121),
        ("daily_message_cap", 100001),
        ("max_message_chars", 99),
        ("max_message_chars", 4001),
        ("history_turns", 1),
        ("history_turns", 51),
        ("daily_token_cap", 0),
        ("paused_message", "x" * 501),
    ],
)
def test_put_validation(admin_client, field, value):
    r = admin_client.put("/api/admin/limits", json={field: value}, headers=csrf(admin_client))
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"] == field


def test_turnstile_toggle_needs_env(admin_client, app):
    r = admin_client.put(
        "/api/admin/limits", json={"turnstile_enabled": True}, headers=csrf(admin_client)
    )
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"] == "turnstile_enabled"
    app.state.settings.turnstile_site_key = "k"
    app.state.settings.turnstile_secret_key = "s"
    r = admin_client.put(
        "/api/admin/limits", json={"turnstile_enabled": True}, headers=csrf(admin_client)
    )
    assert r.json()["turnstile_enabled"] is True and r.json()["turnstile_available"] is True


def test_auth_and_csrf(client, admin_client):
    assert admin_client.put("/api/admin/limits", json={}).status_code == 403
    admin_client.post("/api/auth/logout", headers=csrf(admin_client))
    assert admin_client.get("/api/admin/limits").status_code == 401
    assert admin_client.get("/api/admin/usage").status_code == 401


def test_usage_aggregation(admin_client, app, fake_llm):
    today_ = app.state.chat_limiter.today()
    set_limits(app, per_ip_per_minute=2)
    fake_llm.usage = Usage(prompt_tokens=40, completion_tokens=2)
    sid = new_session(admin_client)
    chat(admin_client, sid)
    fake_llm.usage = None
    chat(admin_client, sid)
    assert chat(admin_client, sid).status_code == 429
    body = admin_client.get("/api/admin/usage?days=7").json()
    assert len(body["days"]) == 7
    today = body["days"][0]
    assert today["date"] == today_.isoformat()
    assert today["messages"] == 2 and today["tokens"] > 42
    assert today["tokens_estimated"] is True
    assert today["rate_limited"] == 1 and today["leak_blocked"] == 0
    assert body["days"][1] == {
        "date": (today_ - timedelta(days=1)).isoformat(),
        "messages": 0,
        "tokens": 0,
        "tokens_estimated": False,
        "rate_limited": 0,
        "leak_blocked": 0,
    }
    [top] = body["top_visitors"]
    assert top["messages"] == 2 and top["ip_hash"].endswith("…") and len(top["ip_hash"]) == 5
    assert "testclient" not in str(body)


def test_usage_days_range(admin_client):
    assert admin_client.get("/api/admin/usage?days=0").status_code == 422
    assert admin_client.get("/api/admin/usage?days=31").status_code == 422
    assert len(admin_client.get("/api/admin/usage").json()["days"]) == 7
