"""Per-tenant hard caps (hosted)."""

import io

from conftest import csrf, make_tenant

from mebot.models import BotLimits


def test_limits_show_caps_and_clamp_defaults(tenants):
    a, _ = tenants
    body = a.client.get("/api/admin/limits").json()
    assert body["caps"]["daily_message_cap"] == 500
    assert body["daily_token_cap"] == 1_000_000  # "off" isn't allowed: the cap applies


def test_owner_can_lower_not_raise(tenants):
    a, _ = tenants
    h = csrf(a.client)
    assert (
        a.client.put("/api/admin/limits", json={"daily_message_cap": 50}, headers=h).status_code
        == 200
    )
    r = a.client.put("/api/admin/limits", json={"daily_message_cap": 501}, headers=h)
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "daily_message_cap"
    r = a.client.put("/api/admin/limits", json={"daily_token_cap": None}, headers=h)
    assert r.status_code == 422


def test_stale_row_above_cap_is_clamped_at_runtime(hosted_settings):
    from mebot.main import create_app

    app = create_app(hosted_settings.model_copy(update={"hosted_max_session_messages": 2}))
    t = make_tenant(app, "alice")
    with app.state.session_factory() as db:
        db.add(BotLimits(bot_id=t.bot_id, per_session_messages=40))
        db.commit()
    c = t.client
    from fastapi.testclient import TestClient

    with TestClient(app) as anon:
        sid = anon.post("/b/alice/api/session", json={}, headers=csrf(anon)).json()["session_id"]
        codes = [
            anon.post(
                "/b/alice/api/chat", json={"session_id": sid, "message": "hi"}, headers=csrf(anon)
            ).status_code
            for _ in range(3)
        ]
    assert codes[:2] == [200, 200] and codes[2] == 429
    del c


def test_single_mode_limits_unchanged(admin_client):
    assert "caps" not in admin_client.get("/api/admin/limits").json()


def test_daily_import_cap(hosted_settings):
    from mebot.main import create_app

    app = create_app(hosted_settings.model_copy(update={"hosted_max_imports_per_day": 1}))
    t = make_tenant(app, "alice")
    calls = []
    app.state.import_day_limiter.hit = lambda key, limit=None: (
        calls.append((key, limit)) or (None if len(calls) == 1 else 3600)
    )
    app.state.import_limiter.hit = lambda key, limit=None: None

    def up(n):
        return t.client.post(
            "/api/admin/import/linkedin",
            files={
                "file": (
                    f"x{n}.zip",
                    io.BytesIO(b"PK\x03\x04" + bytes([n]) * 20),
                    "application/zip",
                )
            },
            headers=csrf(t.client),
        )

    up(1)
    r = up(2)
    assert r.status_code == 429 and "today" in r.json()["error"]["message"]
    assert calls[0] == (t.bot_id, 1)
