import httpx
import pytest
import respx

from mebot import turnstile
from tests.test_chat_limits import set_limits

VERIFY = turnstile.VERIFY_URL


@pytest.fixture
def ts_app(app):
    app.state.settings.turnstile_site_key = "site-key-1"
    app.state.settings.turnstile_secret_key = "ts-secret-SHOULD-NOT-LEAK"
    return app


def test_public_config_defaults(admin_client):
    assert admin_client.get("/api/public/config").json() == {
        "turnstile_site_key": None,
        "max_message_chars": 1000,
        "paused": False,
        "owner_name": "Shivansh",
    }


def test_public_config_reflects_limits(admin_client, ts_app):
    set_limits(ts_app, max_message_chars=500, paused=True)
    body = admin_client.get("/api/public/config").json()
    assert body == {
        "turnstile_site_key": None,
        "max_message_chars": 500,
        "paused": True,
        "owner_name": "Shivansh",
    }
    set_limits(ts_app, turnstile_enabled=True)
    assert admin_client.get("/api/public/config").json()["turnstile_site_key"] == "site-key-1"


def test_public_config_before_setup(client):
    body = client.get("/api/public/config").json()
    assert body["max_message_chars"] == 1000 and body["turnstile_site_key"] is None


def test_turnstile_off_when_env_missing(admin_client, app):
    set_limits(app, turnstile_enabled=True)  # enabled, but no keys configured
    assert admin_client.get("/api/public/config").json()["turnstile_site_key"] is None
    assert admin_client.post("/api/session", json={}).status_code == 200


@respx.mock
def test_session_requires_valid_token(admin_client, ts_app):
    set_limits(ts_app, turnstile_enabled=True)
    route = respx.post(VERIFY).mock(return_value=httpx.Response(200, json={"success": True}))
    r = admin_client.post("/api/session", json={"turnstile_token": "tok-1"})
    assert r.status_code == 200
    sent = route.calls.last.request.content.decode()
    assert "secret=ts-secret-SHOULD-NOT-LEAK" in sent and "response=tok-1" in sent


@respx.mock
def test_session_missing_or_bad_token(admin_client, ts_app):
    set_limits(ts_app, turnstile_enabled=True)
    respx.post(VERIFY).mock(return_value=httpx.Response(200, json={"success": False}))
    for body in ({}, {"turnstile_token": "bad"}):
        r = admin_client.post("/api/session", json=body)
        assert r.status_code == 403
        err = r.json()["error"]
        assert err["code"] == "TURNSTILE_FAILED"
        assert "ts-secret" not in r.text


@respx.mock
def test_session_fails_closed_on_timeout(admin_client, ts_app):
    set_limits(ts_app, turnstile_enabled=True)
    respx.post(VERIFY).mock(side_effect=httpx.ConnectTimeout("slow"))
    r = admin_client.post("/api/session", json={"turnstile_token": "tok"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "TURNSTILE_UNAVAILABLE"


@respx.mock
async def test_verify_uses_5s_timeout(monkeypatch):
    seen = {}
    real = httpx.AsyncClient

    def spy(*a, **kw):
        seen["timeout"] = kw.get("timeout")
        return real(*a, **kw)

    monkeypatch.setattr(turnstile.httpx, "AsyncClient", spy)
    respx.post(VERIFY).mock(return_value=httpx.Response(200, json={"success": True}))
    assert await turnstile.verify("s", "t", "1.2.3.4") is True
    assert seen["timeout"] == 5.0
