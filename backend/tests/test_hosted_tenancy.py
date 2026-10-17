"""Hosted mode: which bot a request acts on (middleware + deps)."""

from datetime import timedelta

from conftest import csrf, make_tenant
from fastapi.testclient import TestClient

from mebot.models import SlugRedirect, utcnow
from mebot.repos import bots


def _cfg(c, prefix):
    return c.get(f"{prefix}/api/public/config")


def test_public_config_by_slug_and_public_key(tenants, hosted_app):
    a, b = tenants
    with TestClient(hosted_app) as anon:
        ra = _cfg(anon, f"/b/{a.slug}")
        rb = _cfg(anon, f"/b/{b.public_key}")
    assert ra.status_code == 200 and rb.status_code == 200
    assert ra.json() != rb.json()
    assert "Alice" in ra.text and "Bobby" not in ra.text
    assert "Bobby" in rb.text


def test_public_route_without_tenant_is_404_for_anonymous(hosted_app, tenants):
    with TestClient(hosted_app) as anon:
        r = anon.get("/api/public/config")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "BOT_UNAVAILABLE"


def test_owner_without_prefix_gets_own_bot(tenants):
    a, _ = tenants
    assert "Alice" in a.client.get("/api/public/config").text


def test_unknown_suspended_unverified_unsetup_all_neutral_404(hosted_app):
    make_tenant(hosted_app, "suspd", status="suspended")
    make_tenant(hosted_app, "unver", verified=False)
    make_tenant(hosted_app, "nosetup", setup_done=False)
    with TestClient(hosted_app) as anon:
        bodies = [_cfg(anon, f"/b/{s}") for s in ("nobody", "suspd", "unver", "nosetup")]
    assert {r.status_code for r in bodies} == {404}
    assert len({r.text for r in bodies}) == 1  # no reason leaks


def test_tenant_prefix_cannot_reach_owner_apis(tenants):
    a, b = tenants
    for path in ("/api/admin/profile", "/api/auth/me", "/api/setup/status", "/widget-test"):
        r = a.client.get(f"/b/{b.slug}{path}")
        assert r.status_code == 404, path


def test_admin_routes_ignore_subdomain_of_other_tenant(hosted_settings):
    from mebot.main import create_app

    app = create_app(hosted_settings.model_copy(update={"hosted_domain": "bots.example"}))
    a, b = make_tenant(app, "alice"), make_tenant(app, "bobby")
    r = b.client.get("/api/public/config", headers={"host": "alice.bots.example"})
    assert r.status_code == 200 and "Alice" in r.text
    # B's session on A's host: admin APIs are not public -> 404, never A's data.
    assert (
        b.client.get("/api/admin/profile", headers={"host": "alice.bots.example"}).status_code
        == 404
    )
    assert "Bobby" in b.client.get("/api/auth/me").text
    del a


def test_old_slug_redirects_301(tenants, hosted_app):
    a, _ = tenants
    with hosted_app.state.session_factory() as db:
        db.add(
            SlugRedirect(
                old_slug="oldalice", bot_id=a.bot_id, expires_at=utcnow() + timedelta(days=30)
            )
        )
        db.add(
            SlugRedirect(old_slug="gone", bot_id=a.bot_id, expires_at=utcnow() - timedelta(days=1))
        )
        db.commit()
    with TestClient(hosted_app, follow_redirects=False) as anon:
        r = anon.get("/b/oldalice/api/public/config?x=1")
        assert r.status_code == 301
        assert r.headers["location"] == f"/b/{a.slug}/api/public/config?x=1"
        assert anon.get("/b/gone/api/public/config").status_code == 404


def test_single_mode_b_prefix_404(client):
    assert client.get("/b/anything/api/public/config").status_code == 404


def test_session_bound_to_bot(tenants, hosted_app):
    a, b = tenants
    with hosted_app.state.session_factory() as db:
        from mebot.models import Admin

        admin = db.query(Admin).filter_by(email=a.email).one()
        admin.bot_id = b.bot_id  # session was created for A's bot
        db.commit()
    assert a.client.get("/api/auth/me").status_code == 401


def test_suspended_tenant_session_dies(tenants, hosted_app):
    a, _ = tenants
    with hosted_app.state.session_factory() as db:
        bots.get(db, a.bot_id).status = "suspended"
        db.commit()
    assert a.client.get("/api/auth/me").status_code == 401


def test_chat_via_prefix_lands_in_right_bot(tenants, hosted_app):
    a, b = tenants
    with TestClient(hosted_app) as anon:
        r = anon.post(f"/b/{b.slug}/api/session", json={}, headers=csrf(anon))
        assert r.status_code in (200, 201), r.text
        sid = r.json()["session_id"]
    with hosted_app.state.session_factory() as db:
        from mebot.models import ChatSession

        assert db.get(ChatSession, sid).bot_id == b.bot_id
