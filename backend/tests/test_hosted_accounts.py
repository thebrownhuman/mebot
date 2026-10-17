"""Hosted sign-up, verification, password reset, invites."""

from datetime import timedelta

import pytest
from conftest import ADMIN_PASSWORD, csrf, make_tenant, setup_body
from fastapi.testclient import TestClient

from mebot.hosted.mailer import ConsoleMailer
from mebot.main import create_app
from mebot.models import Admin, Bot, PasswordReset, utcnow
from mebot.repos import invites


@pytest.fixture
def ts_ok(monkeypatch):
    calls = []

    async def fake_verify(secret, token, ip):
        calls.append(token)
        return token == "good"

    monkeypatch.setattr("mebot.turnstile.verify", fake_verify)
    return calls


@pytest.fixture
def anon(hosted_app, ts_ok):
    hosted_app.state.mailer = ConsoleMailer()
    with TestClient(hosted_app) as c:
        yield c


def _body(**over):
    b = {
        "email": "new@example.com",
        "password": ADMIN_PASSWORD,
        "bot_name": "New Owner",
        "slug": "new-owner",
        "turnstile_token": "good",
    }
    b.update(over)
    return b


def signup(c, **over):
    return c.post("/api/hosted/signup", json=_body(**over), headers=csrf(c))


def _token_from(mail) -> str:
    return mail.body.split("token=")[1].split()[0]


def _db(c):
    return c.app.state.session_factory()


def _app(settings, **over):
    app = create_app(settings.model_copy(update=over))
    app.state.mailer = ConsoleMailer()
    return app


def test_signup_sends_verification_and_bot_not_live_until_verified(anon):
    r = signup(anon)
    assert r.status_code == 202, r.text
    mail = anon.app.state.mailer.sent[-1]
    assert mail.to == "new@example.com" and "/verify?token=" in mail.body
    with _db(anon) as db:
        bot = db.query(Bot).filter_by(slug="new-owner").one()
        admin = db.query(Admin).filter_by(email="new@example.com").one()
        assert admin.bot_id == bot.id and admin.email_verified_at is None
        assert bot.plan == "free" and bot.status == "active"
    assert anon.get("/b/new-owner/api/public/config").status_code == 404
    r = anon.post("/api/hosted/verify", json={"token": _token_from(mail)}, headers=csrf(anon))
    assert r.status_code == 204
    with _db(anon) as db:
        assert db.query(Admin).filter_by(email="new@example.com").one().email_verified_at


def test_verify_token_single_use_and_bad(anon):
    signup(anon)
    tok = _token_from(anon.app.state.mailer.sent[-1])
    h = csrf(anon)
    assert anon.post("/api/hosted/verify", json={"token": tok}, headers=h).status_code == 204
    assert anon.post("/api/hosted/verify", json={"token": tok}, headers=h).status_code == 400
    assert anon.post("/api/hosted/verify", json={"token": "nope"}, headers=h).status_code == 400


def test_signup_then_login_sees_own_bot(anon):
    signup(anon)
    r = anon.post(
        "/api/auth/login",
        json={"email": "new@example.com", "password": ADMIN_PASSWORD},
        headers=csrf(anon),
    )
    assert r.status_code == 204
    assert anon.get("/api/auth/me").json()["bot_slug"] == "new-owner"


def test_existing_email_same_answer_no_second_account(anon, hosted_app):
    make_tenant(hosted_app, "alice")
    r = signup(anon, email="alice@example.com", slug="another")
    assert r.status_code == 202 and r.json() == {"status": "check_your_email"}
    assert "already have" in anon.app.state.mailer.sent[-1].subject
    with _db(anon) as db:
        assert db.query(Bot).filter_by(slug="another").count() == 0


def test_slug_rules(anon, hosted_app):
    make_tenant(hosted_app, "alice")
    assert signup(anon, slug="alice").status_code == 409
    for bad in ("ab", "admin", "has_under", "-lead", "a--b", "x" * 33):
        assert signup(anon, slug=bad).status_code == 422, bad


def test_turnstile_required_and_checked(anon, ts_ok):
    assert signup(anon, turnstile_token=None).status_code == 400
    assert signup(anon, turnstile_token="bad").json()["error"]["code"] == "TURNSTILE_FAILED"
    assert ts_ok == ["bad"]


def test_turnstile_not_configured_refuses(hosted_settings, ts_ok):
    with TestClient(_app(hosted_settings, turnstile_secret_key=None)) as c:
        assert signup(c).status_code == 503


def test_signup_rate_limited_per_ip(anon):
    codes = [signup(anon, email=f"u{i}@x.io", slug=f"user-{i}").status_code for i in range(6)]
    assert codes[:5] == [202] * 5 and codes[5] == 429


def test_closed_mode(hosted_settings, ts_ok):
    with TestClient(_app(hosted_settings, signup_mode="closed")) as c:
        assert signup(c).status_code == 403


def test_invite_mode(hosted_settings, ts_ok):
    app = _app(hosted_settings, signup_mode="invite")
    with app.state.session_factory() as db:
        code = invites.create(db, note="for new")
        db.commit()
    with TestClient(app) as c:
        assert signup(c, invite_code="wrong").status_code == 400
        assert signup(c, invite_code=code).status_code == 202
        assert signup(c, invite_code=code, email="z@x.io", slug="zed-z").status_code == 400


def test_single_mode_has_no_hosted_routes(client):
    r = client.post("/api/hosted/signup", json=_body(), headers=csrf(client))
    assert r.status_code == 404
    assert client.get("/api/hosted/config").status_code == 404


def test_hosted_disables_global_setup(anon):
    assert anon.get("/api/setup/status").json()["setup_required"] is False
    assert anon.post("/api/setup", json=setup_body(), headers=csrf(anon)).status_code == 404


def _reset(c, email):
    return c.post("/api/hosted/password-reset", json={"email": email}, headers=csrf(c))


def _confirm(c, token, pw="a brand new password"):
    return c.post(
        "/api/hosted/password-reset/confirm",
        json={"token": token, "new_password": pw},
        headers=csrf(c),
    )


def test_password_reset_single_use_and_revokes_sessions(anon, hosted_app):
    t = make_tenant(hosted_app, "alice")
    sent = anon.app.state.mailer.sent
    assert _reset(anon, "nobody@x.io").status_code == 202  # same answer, no mail
    n = len(sent)
    assert _reset(anon, "alice@example.com").status_code == 202
    assert len(sent) == n + 1
    tok = _token_from(sent[-1])
    assert _confirm(anon, tok).status_code == 204
    assert _confirm(anon, tok).status_code == 400  # single use
    assert t.client.get("/api/auth/me").status_code == 401  # old sessions gone
    r = anon.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": "a brand new password"},
        headers=csrf(anon),
    )
    assert r.status_code == 204


def test_password_reset_expires(anon, hosted_app):
    make_tenant(hosted_app, "alice")
    _reset(anon, "alice@example.com")
    tok = _token_from(anon.app.state.mailer.sent[-1])
    with _db(anon) as db:
        db.query(PasswordReset).one().expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert _confirm(anon, tok).status_code == 400


def test_new_reset_link_replaces_old(anon, hosted_app):
    make_tenant(hosted_app, "alice")
    _reset(anon, "alice@example.com")
    first = _token_from(anon.app.state.mailer.sent[-1])
    _reset(anon, "alice@example.com")
    assert _confirm(anon, first).status_code == 400


def test_resend_verification(anon):
    signup(anon)
    n = len(anon.app.state.mailer.sent)
    r = anon.post(
        "/api/hosted/verify/resend", json={"email": "new@example.com"}, headers=csrf(anon)
    )
    assert r.status_code == 202 and len(anon.app.state.mailer.sent) == n + 1
