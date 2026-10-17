"""Platform operator (hosted): auth, tenant actions, audit, approval queue, pings, and
the guarantee that the operator can't reach tenant content."""

import json
import re

import httpx
import pytest
import respx
from conftest import ADMIN_PASSWORD, LLM_KEY, csrf, make_tenant
from fastapi.testclient import TestClient

from mebot import cli
from mebot.auth import passwords
from mebot.hosted import operator as op
from mebot.hosted.mailer import ConsoleMailer
from mebot.models import Message, PlatformAudit, Skill, UsageCounter

OP_EMAIL = "ops@example.com"
OP_PASSWORD = "operator password 1"
MARK = "ZQXCONTENTSECRET"
CONTENT_WORDS = re.compile(r"conversation|message|profile|prompt|llm|key|contact|fact|chunk")


def _operator(app):
    with app.state.session_factory() as db:
        op.create_admin(db, OP_EMAIL, passwords.hash_password(OP_PASSWORD))
        db.commit()
    c = TestClient(app)
    c.__enter__()
    r = c.post(
        "/api/platform/auth/login",
        json={"email": OP_EMAIL, "password": OP_PASSWORD},
        headers=csrf(c),
    )
    assert r.status_code == 204, r.text
    return c


@pytest.fixture
def ops(hosted_app):
    hosted_app.state.mailer = ConsoleMailer()
    c = _operator(hosted_app)
    yield c
    c.__exit__(None, None, None)


def _seed_content(app, bot_id):
    with app.state.session_factory() as db:
        db.add(Skill(bot_id=bot_id, name=MARK))
        db.add(Message(bot_id=bot_id, session_id="s1", role="user", content=MARK))
        db.add(
            UsageCounter(
                bot_id=bot_id, scope="bot_day", key="*", window_start="2099-01-01",
                messages=7, tokens=900,
            )
        )  # fmt: skip
        db.commit()


def _audit(app):
    with app.state.session_factory() as db:
        return [a.action for a in db.query(PlatformAudit).order_by(PlatformAudit.created_at)]


def test_login_required_and_tenant_session_is_not_an_operator(tenants, hosted_app):
    a, _ = tenants
    with TestClient(hosted_app) as anon:
        assert anon.get("/api/platform/tenants").status_code == 401
    assert a.client.get("/api/platform/tenants").status_code == 401  # tenant cookie
    bad = TestClient(hosted_app)
    r = bad.post(
        "/api/platform/auth/login", json={"email": OP_EMAIL, "password": "x"}, headers=csrf(bad)
    )
    assert r.status_code == 401


def test_operator_session_is_not_a_tenant_admin(ops):
    assert ops.get("/api/auth/me").status_code == 401
    assert ops.get("/api/admin/profile/identity").status_code == 401


def test_tenant_list_has_usage_but_no_content(ops, tenants, hosted_app):
    a, _ = tenants
    _seed_content(hosted_app, a.bot_id)
    items = ops.get("/api/platform/tenants").json()["items"]
    row = next(t for t in items if t["slug"] == "alice")
    assert row["messages_7d"] == 7 and row["tokens_30d"] == 900
    assert row["owner_email"] == a.email and row["plan"] == "free"
    assert row["last_active_at"]


def test_operator_cannot_reach_keys_profiles_or_conversations(ops, tenants, hosted_app):
    """No platform route is about content, and none returns any (enumerated)."""
    a, _ = tenants
    _seed_content(hosted_app, a.bot_id)
    paths = [p for p in hosted_app.openapi()["paths"] if p.startswith("/api/platform")]
    assert len(paths) >= 8
    for p in paths:
        assert not CONTENT_WORDS.search(p), p
    for p, ops_ in hosted_app.openapi()["paths"].items():
        if not p.startswith("/api/platform") or "get" not in ops_:
            continue
        r = ops.get(p.replace("{bot_id}", a.bot_id))
        assert MARK not in r.text and LLM_KEY not in r.text and "sk-" not in r.text, p
    # And the tenant's own content routes stay closed to the operator.
    for p in ("/api/admin/conversations", "/api/admin/llm", "/api/admin/profile/preview"):
        assert ops.get(p).status_code == 401


@respx.mock
def test_suspend_with_reason_pings_and_kills_sessions(ops, tenants, hosted_app):
    hosted_app.state.settings.platform_telegram_bot_token = "1:PLATFORM"
    hosted_app.state.settings.platform_telegram_chat_id = "42"
    tg = respx.post(url__regex=r"https://api\.telegram\.org/bot1:PLATFORM/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    )
    a, _ = tenants
    h = csrf(ops)
    r = ops.post(f"/api/platform/tenants/{a.bot_id}/suspend", json={"reason": "spam"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    assert a.client.get("/api/auth/me").status_code == 401
    with TestClient(hosted_app) as anon:
        r = anon.get("/b/alice/api/public/config")
        assert r.status_code == 404 and "spam" not in r.text  # reason never public
    row = next(t for t in ops.get("/api/platform/tenants").json()["items"] if t["slug"] == "alice")
    assert row["status_reason"] == "spam"
    assert "alice" in json.loads(tg.calls.last.request.content)["text"]
    r = ops.post(f"/api/platform/tenants/{a.bot_id}/unsuspend", headers=h)
    assert r.json()["status"] == "active"
    assert _audit(hosted_app)[-2:] == ["suspend", "unsuspend"]


def test_ping_is_best_effort(ops, tenants, hosted_app):
    hosted_app.state.settings.platform_telegram_bot_token = "1:DOWN"
    hosted_app.state.settings.platform_telegram_chat_id = "42"
    a, _ = tenants
    with respx.mock:
        respx.post(url__regex=r".*sendMessage").mock(side_effect=httpx.ConnectError("down"))
        r = ops.post(
            f"/api/platform/tenants/{a.bot_id}/suspend", json={"reason": "x"}, headers=csrf(ops)
        )
    assert r.status_code == 200


def test_delete_and_resend_verification(ops, hosted_app):
    t = make_tenant(hosted_app, "unver", verified=False)
    h = csrf(ops)
    r = ops.post(f"/api/platform/tenants/{t.bot_id}/resend-verification", headers=h)
    assert r.status_code == 200
    assert "/verify?token=" in hosted_app.state.mailer.sent[-1].body
    r = ops.post(f"/api/platform/tenants/{t.bot_id}/delete", json={"reason": "abuse"}, headers=h)
    assert r.json()["status"] == "deleted"
    assert t.client.get("/api/auth/me").status_code == 401
    assert ops.post("/api/platform/tenants/nope/unsuspend", headers=h).status_code == 404
    assert {"resend_verification", "delete"} <= set(_audit(hosted_app))


def test_invites_create_list_revoke(ops, hosted_app):
    h = csrf(ops)
    code = ops.post("/api/platform/invites", json={"note": "for sam"}, headers=h).json()["code"]
    items = ops.get("/api/platform/invites").json()["items"]
    assert items[0]["note"] == "for sam" and code not in json.dumps(items)  # hash only
    assert ops.delete(f"/api/platform/invites/{items[0]['id']}", headers=h).status_code == 204
    assert ops.get("/api/platform/invites").json()["items"] == []
    assert _audit(hosted_app)[-2:] == ["invite_created", "invite_revoked"]


def test_audit_log_lists_actions(ops, tenants):
    a, _ = tenants
    ops.post(f"/api/platform/tenants/{a.bot_id}/suspend", json={"reason": "r"}, headers=csrf(ops))
    items = ops.get("/api/platform/audit").json()["items"]
    assert items[0]["action"] == "suspend" and items[0]["tenant"] == "alice"
    assert items[0]["actor"] == OP_EMAIL and items[0]["detail"] == "r"


@pytest.fixture
def ts_ok(monkeypatch):
    async def fake_verify(secret, token, ip):
        return True

    monkeypatch.setattr("mebot.turnstile.verify", fake_verify)


def test_invite_mode_queue_then_approve_sends_mail(hosted_settings, ts_ok):
    from mebot.main import create_app

    app = create_app(hosted_settings.model_copy(update={"signup_mode": "invite"}))
    app.state.mailer = ConsoleMailer()
    body = {
        "email": "q@example.com",
        "password": ADMIN_PASSWORD,
        "bot_name": "Queued",
        "slug": "queued",
        "turnstile_token": "t",
    }
    with TestClient(app) as c:
        r = c.post("/api/hosted/signup", json=body, headers=csrf(c))
        assert r.status_code == 202 and r.json()["approval_required"] is True
        r = c.post(
            "/api/auth/login",
            json={"email": "q@example.com", "password": ADMIN_PASSWORD},
            headers=csrf(c),
        )
        assert r.status_code == 403 and r.json()["error"]["code"] == "PENDING_APPROVAL"
    ops = _operator(app)
    queue = ops.get("/api/platform/signups").json()["items"]
    assert [t["slug"] for t in queue] == ["queued"]
    assert all(t["slug"] != "queued" for t in ops.get("/api/platform/tenants").json()["items"])
    r = ops.post(f"/api/platform/tenants/{queue[0]['id']}/approve", headers=csrf(ops))
    assert r.json()["status"] == "active"
    assert app.state.mailer.sent[-1].subject == "Your mebot account is approved"
    assert (
        ops.post(f"/api/platform/tenants/{queue[0]['id']}/approve", headers=csrf(ops)).status_code
        == 409
    )
    assert ops.get("/api/platform/signups").json()["items"] == []


@respx.mock
def test_signup_pings_maintainer(hosted_settings, ts_ok):
    from mebot.main import create_app

    app = create_app(
        hosted_settings.model_copy(
            update={"platform_telegram_bot_token": "1:P", "platform_telegram_chat_id": "9"}
        )
    )
    app.state.mailer = ConsoleMailer()
    tg = respx.post(url__regex=r".*bot1:P/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    )
    body = {
        "email": "n@example.com", "password": ADMIN_PASSWORD, "bot_name": "N",
        "slug": "newbie", "turnstile_token": "t",
    }  # fmt: skip
    with TestClient(app) as c:
        assert c.post("/api/hosted/signup", json=body, headers=csrf(c)).status_code == 202
    assert "newbie" in json.loads(tg.calls.last.request.content)["text"]


def test_platform_routes_404_in_single_mode(client):
    assert client.get("/api/platform/tenants").status_code == 404


def test_cli_platform_admin_create(hosted_settings, monkeypatch, capsys):
    from mebot.db import make_session_factory

    answers = iter([OP_PASSWORD, OP_PASSWORD])
    monkeypatch.setattr(cli, "Settings", lambda: hosted_settings)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))
    assert cli.main(["platform-admin", "create", "Boss@Example.com"]) == 0
    with make_session_factory(hosted_settings.database_url)() as db:
        admin = op.get_by_email(db, "boss@example.com")
        assert admin is not None
    assert cli.main(["platform-admin", "create", "boss@example.com"]) == 1  # exists


def test_cli_platform_admin_refused_in_single_mode(settings, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    assert cli.main(["platform-admin", "create", "x@example.com"]) == 1
