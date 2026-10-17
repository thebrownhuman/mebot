"""Hosted mode: public chat/session APIs only answer pages on the platform itself or on a
site the owner allowed (Admin -> Widget). Anything else is the neutral BOT_UNAVAILABLE."""

import json

import pytest
from fastapi.testclient import TestClient

from mebot.models import WidgetSettings
from tests.conftest import csrf, make_tenant


@pytest.fixture
def alice(hosted_app):
    t = make_tenant(hosted_app, "alice")
    yield t
    t.client.__exit__(None, None, None)


def _allow(app, bot_id, origins, any_origin=False):
    with app.state.session_factory() as db:
        row = db.query(WidgetSettings).filter_by(bot_id=bot_id).one_or_none()
        if row is None:
            row = WidgetSettings(bot_id=bot_id)
            db.add(row)
        row.allowed_origins = json.dumps(origins)
        row.allow_any_origin = any_origin
        db.commit()


def _session(c, origin=None, ref="alice"):
    headers = csrf(c)
    if origin:
        headers["Origin"] = origin
    return c.post(f"/b/{ref}/api/session", json={}, headers=headers)


def test_platform_origin_and_no_origin_pass(hosted_app, alice):
    with TestClient(hosted_app) as c:
        assert _session(c).status_code in (200, 201)
        assert _session(c, "http://testserver").status_code in (200, 201)
        assert _session(c, "https://mebot.example").status_code in (200, 201)  # PUBLIC_URL


def test_unknown_origin_is_neutral_unavailable(hosted_app, alice):
    with TestClient(hosted_app) as c:
        bad = _session(c, "https://evil.example")
        bad_cfg = c.get("/b/alice/api/public/config", headers={"Origin": "https://evil.example"})
        unknown = c.get("/b/nobody/api/public/config")
    assert bad.status_code == bad_cfg.status_code == 404
    assert bad.text == unknown.text  # same body as an unknown bot


def test_allowed_site_and_wildcard_and_any(hosted_app, alice):
    _allow(hosted_app, alice.bot_id, ["https://alice.dev", "https://*.blog.io"])
    with TestClient(hosted_app) as c:
        assert _session(c, "https://alice.dev", ref=alice.public_key).status_code in (200, 201)
        assert _session(c, "https://x.blog.io").status_code in (200, 201)
        assert _session(c, "https://other.dev").status_code == 404
    _allow(hosted_app, alice.bot_id, [], any_origin=True)
    with TestClient(hosted_app) as c:
        assert _session(c, "https://other.dev").status_code in (200, 201)


def test_single_mode_untouched(admin_client):
    r = admin_client.post(
        "/api/session", json={}, headers={**csrf(admin_client), "Origin": "https://evil.example"}
    )
    assert r.status_code != 404 or r.json()["error"]["code"] != "BOT_UNAVAILABLE"
