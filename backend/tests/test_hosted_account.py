"""Hosted owner account: per-tenant setup, slug change, export, deletion + purge."""

import io
import json
import zipfile
from datetime import timedelta

from conftest import ADMIN_PASSWORD, LLM, csrf, make_tenant
from fastapi.testclient import TestClient

from mebot.hosted import purge
from mebot.models import Admin, Bot, Message, Skill, SlugRedirect, utcnow
from mebot.repos import bots


def test_new_tenant_setup_goes_live(hosted_app):
    t = make_tenant(hosted_app, "fresh", setup_done=False)
    c = t.client
    acct = c.get("/api/hosted/account").json()
    assert acct["setup_done"] is False and acct["live"] is False
    body = {"bot_name": "Fresh Owner", "full_name": "Fresh Owner", "llm": dict(LLM)}
    r = c.post("/api/hosted/account/setup", json=body, headers=csrf(c))
    assert r.status_code == 200, r.text
    assert r.json()["live"] is True
    assert c.post("/api/hosted/account/setup", json=body, headers=csrf(c)).status_code == 409
    with TestClient(hosted_app) as anon:
        assert anon.get("/b/fresh/api/public/config").status_code == 200


def test_setup_llm_failure_saves_nothing(hosted_app, fake_llm):
    from mebot.llm.base import LLMError

    fake_llm.fail = LLMError("auth", "bad key")
    t = make_tenant(hosted_app, "fresh", setup_done=False)
    body = {"bot_name": "X", "llm": dict(LLM)}
    r = t.client.post("/api/hosted/account/setup", json=body, headers=csrf(t.client))
    assert r.status_code == 422
    assert t.client.get("/api/hosted/account").json()["setup_done"] is False


def test_slug_change_keeps_301_and_frees_nothing_for_others(tenants, hosted_app):
    a, b = tenants
    r = a.client.put("/api/hosted/account/slug", json={"slug": "alice-new"}, headers=csrf(a.client))
    assert r.status_code == 200 and r.json()["slug"] == "alice-new"
    with TestClient(hosted_app, follow_redirects=False) as anon:
        r = anon.get("/b/alice/api/public/config")
        assert r.status_code == 301 and r.headers["location"] == "/b/alice-new/api/public/config"
        assert (
            anon.get(f"/api/public/widget/{a.public_key}").status_code == 200
        )  # embeds unaffected
    # B can't take A's old slug while the redirect lives; A can take it back.
    rb = b.client.put("/api/hosted/account/slug", json={"slug": "alice"}, headers=csrf(b.client))
    assert rb.status_code == 409
    ra = a.client.put("/api/hosted/account/slug", json={"slug": "alice"}, headers=csrf(a.client))
    assert ra.status_code == 200
    assert (
        b.client.put(
            "/api/hosted/account/slug", json={"slug": "admin"}, headers=csrf(b.client)
        ).status_code
        == 422
    )


def test_export_contains_own_content_only_no_secrets(tenants, hosted_app):
    a, b = tenants
    with hosted_app.state.session_factory() as db:
        db.add(Skill(bot_id=a.bot_id, name="ALICE-SKILL"))
        db.add(Skill(bot_id=b.bot_id, name="BOB-SKILL"))
        db.commit()
    r = a.client.get("/api/hosted/account/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"skills.json", "learned_facts.json", "messages.json", "sessions.json"} <= names
    assert "llm_configs.json" not in names and "telegram_configs.json" not in names
    blob = b"".join(z.read(n) for n in names)
    assert b"ALICE-SKILL" in blob and b"BOB-SKILL" not in blob
    assert b"sk-test" not in blob
    assert json.loads(z.read("skills.json"))[0]["name"] == "ALICE-SKILL"


def test_delete_needs_password_then_offline_and_logged_out(tenants, hosted_app):
    a, _ = tenants
    h = csrf(a.client)
    r = a.client.post("/api/hosted/account/delete", json={"password": "wrong"}, headers=h)
    assert r.status_code == 400
    r = a.client.post("/api/hosted/account/delete", json={"password": ADMIN_PASSWORD}, headers=h)
    assert r.status_code == 204
    assert a.client.get("/api/auth/me").status_code == 401
    with TestClient(hosted_app) as anon:
        assert anon.get("/b/alice/api/public/config").status_code == 404
        assert anon.get(f"/api/public/widget/{a.public_key}").status_code == 404
        r = anon.post(
            "/api/auth/login",
            json={"email": a.email, "password": ADMIN_PASSWORD},
            headers=csrf(anon),
        )
        assert r.status_code == 401


def test_purge_after_grace_erases_tenant_only(tenants, hosted_app):
    a, b = tenants
    with hosted_app.state.session_factory() as db:
        db.add(Message(bot_id=a.bot_id, session_id="s", role="user", content="A"))
        db.add(Message(bot_id=b.bot_id, session_id="s", role="user", content="B"))
        bot = bots.get(db, a.bot_id)
        bot.status = "deleted"
        bot.deletion_requested_at = utcnow() - timedelta(days=6)
        db.add(SlugRedirect(old_slug="zz-old", bot_id=b.bot_id, expires_at=utcnow() - timedelta(1)))
        db.commit()
    factory = hosted_app.state.session_factory
    assert purge.purge_deleted(factory, timedelta(days=7)) == 0  # still in grace
    assert purge.purge_deleted(factory, timedelta(days=7), now=utcnow() + timedelta(days=2)) == 1
    with factory() as db:
        assert db.get(Bot, a.bot_id) is None
        assert db.query(Admin).filter_by(bot_id=a.bot_id).count() == 0
        assert {m.content for m in db.query(Message)} == {"B"}
        assert db.get(Bot, b.bot_id) is not None
        assert db.query(SlugRedirect).count() == 0


def test_account_routes_404_in_single_mode(admin_client):
    assert admin_client.get("/api/hosted/account").status_code == 404
