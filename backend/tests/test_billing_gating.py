"""Paid plans: serving gate, trial (days / messages / one per e-mail), plan limits."""

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from mebot.billing import service
from mebot.hosted import purge
from mebot.hosted.mailer import ConsoleMailer
from mebot.main import create_app
from mebot.models import BotLimits, Plan, Subscription, TrialClaim, utcnow
from tests.billing_helpers import sub_row
from tests.conftest import ADMIN_PASSWORD, csrf, make_tenant


@pytest.fixture
def ts_ok(monkeypatch):
    async def fake_verify(secret, token, ip):
        return token == "good"

    monkeypatch.setattr("mebot.turnstile.verify", fake_verify)


def _set_sub(app, bot_id, **fields):
    with app.state.session_factory() as db:
        sub = service.ensure_sub(db, bot_id)
        for k, v in fields.items():
            setattr(sub, k, v)
        db.commit()


def _cfg(c, slug):
    return c.get(f"/b/{slug}/api/public/config")


def _chat(c, slug, n=1):
    r = c.post(f"/b/{slug}/api/session", json={}, headers=csrf(c))
    assert r.status_code in (200, 201), r.text
    sid = r.json()["session_id"]
    out = []
    for i in range(n):
        out.append(
            c.post(
                f"/b/{slug}/api/chat",
                json={"session_id": sid, "message": f"hello {i}"},
                headers=csrf(c),
            )
        )
    return out


def _signup(c, email="new@example.com", slug="new-owner", **over):
    body = {
        "email": email, "password": ADMIN_PASSWORD, "bot_name": "New", "slug": slug,
        "turnstile_token": "good", "accept_terms": True, **over,
    }  # fmt: skip
    return c.post("/api/hosted/signup", json=body, headers=csrf(c))


# --- billing off: nothing changes -------------------------------------------------------


def test_billing_off_serves_without_subscription_and_ignores_plans(hosted_app):
    t = make_tenant(hosted_app, "alice")
    with hosted_app.state.session_factory() as db:
        db.get(Plan, "trial").limits = json.dumps({"daily_message_cap": 1})
        db.commit()
    with TestClient(hosted_app) as anon:
        assert _cfg(anon, "alice").status_code == 200
        assert all(r.status_code == 200 for r in _chat(anon, "alice", 2))
    assert t.client.get("/api/admin/limits").json()["caps"]["daily_message_cap"] == 500
    with hosted_app.state.session_factory() as db:
        assert db.query(Subscription).count() == 0
    t.client.__exit__(None, None, None)


def test_single_mode_untouched(admin_client):
    assert admin_client.get("/api/public/config").status_code == 200
    assert "caps" not in admin_client.get("/api/admin/limits").json()


# --- gate ------------------------------------------------------------------------------


def test_unpaid_is_the_same_neutral_404_as_suspended(billing_app):
    unpaid = make_tenant(billing_app, "unpaid")
    _set_sub(billing_app, unpaid.bot_id, status="inactive")
    make_tenant(billing_app, "suspd", status="suspended")
    paid = make_tenant(billing_app, "paid")
    _set_sub(billing_app, paid.bot_id, status="active")
    with TestClient(billing_app) as anon:
        unpaid_r, suspended_r = _cfg(anon, "unpaid"), _cfg(anon, "suspd")
        assert _cfg(anon, "paid").status_code == 200
        wid = make_tenant(billing_app, "wid")
        _set_sub(billing_app, wid.bot_id, status="none")
        widget = anon.get(f"/api/public/widget/{wid.public_key}")
    assert unpaid_r.status_code == suspended_r.status_code == 404
    assert unpaid_r.text == suspended_r.text
    assert widget.status_code == 404


def test_owner_admin_still_works_when_unpaid(billing_app):
    t = make_tenant(billing_app, "alice")
    _set_sub(billing_app, t.bot_id, status="inactive")
    assert t.client.get("/api/admin/limits").status_code == 200
    acct = t.client.get("/api/hosted/account").json()
    assert acct["serving"] is False and acct["live"] is False and acct["billing_enabled"]
    assert t.client.get("/api/hosted/account/export").status_code == 200


@pytest.mark.parametrize(
    "fields,serving",
    [
        ({"status": "past_due", "grace_until": utcnow() + timedelta(days=1)}, True),
        ({"status": "past_due", "grace_until": utcnow() - timedelta(seconds=1)}, False),
        ({"status": "cancelled", "current_period_end": utcnow() + timedelta(days=3)}, True),
        ({"status": "cancelled", "current_period_end": utcnow() - timedelta(days=1)}, False),
        ({"status": "inactive", "comp_until": utcnow() + timedelta(days=2)}, True),
    ],
)
def test_grace_period_end_and_comp(billing_app, fields, serving):
    t = make_tenant(billing_app, "alice")
    _set_sub(billing_app, t.bot_id, **fields)
    with TestClient(billing_app) as anon:
        assert (_cfg(anon, "alice").status_code == 200) is serving


# --- trial -------------------------------------------------------------------------------


def test_signup_starts_trial_and_needs_terms(billing_app, ts_ok):
    billing_app.state.mailer = ConsoleMailer()
    with TestClient(billing_app) as c:
        r = _signup(c, accept_terms=False)
        assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "accept_terms"
        assert _signup(c).status_code == 202
        cfg = c.get("/api/hosted/config").json()
    assert cfg["billing_enabled"] and cfg["terms_version"] == "2026-10"
    with billing_app.state.session_factory() as db:
        from mebot.models import Admin

        admin = db.query(Admin).filter_by(email="new@example.com").one()
        assert admin.terms_version == "2026-10" and admin.terms_accepted_at is not None
        sub = service.get_sub(db, admin.bot_id)
        assert sub.status == "trialing" and sub.plan_code == "trial"
        assert timedelta(days=13) < sub.trial_ends_at - utcnow() <= timedelta(days=14)
        assert db.query(TrialClaim).count() == 1


def test_one_trial_per_email_survives_deletion(billing_app, ts_ok):
    billing_app.state.mailer = ConsoleMailer()
    with TestClient(billing_app) as c:
        assert _signup(c, email="Re.Peat+x@gmail.com").status_code == 202
    with billing_app.state.session_factory() as db:
        from mebot.models import Admin, Bot

        admin = db.query(Admin).filter_by(email="re.peat+x@gmail.com").one()
        bot = db.get(Bot, admin.bot_id)
        bot.status, bot.deletion_requested_at = "deleted", utcnow() - timedelta(days=30)
        admin.deleted_at = utcnow()
        db.commit()
    purge.purge_deleted(billing_app.state.session_factory, timedelta(days=7))
    with TestClient(billing_app) as c:
        assert _signup(c, email="repeat@gmail.com", slug="again").status_code == 202
    with billing_app.state.session_factory() as db:
        from mebot.models import Admin

        admin = db.query(Admin).filter_by(email="repeat@gmail.com").one()
        assert service.get_sub(db, admin.bot_id).status == "none"  # must subscribe


def test_trial_ends_by_days(billing_app):
    t = make_tenant(billing_app, "alice")
    _set_sub(billing_app, t.bot_id, status="trialing", trial_ends_at=utcnow() + timedelta(hours=1))
    with TestClient(billing_app) as anon:
        assert _cfg(anon, "alice").status_code == 200
        _set_sub(billing_app, t.bot_id, trial_ends_at=utcnow() - timedelta(seconds=1))
        assert _cfg(anon, "alice").status_code == 404


def test_trial_ends_by_messages_and_warns_at_80_percent(billing_settings):
    app = create_app(billing_settings.model_copy(update={"trial_messages": 5}))
    app.state.mailer = mailer = ConsoleMailer()
    t = make_tenant(app, "alice")
    _set_sub(app, t.bot_id, status="trialing", trial_ends_at=utcnow() + timedelta(days=9))
    with TestClient(app) as anon:
        replies = _chat(anon, "alice", 5)
        assert all(r.status_code == 200 for r in replies)
        assert sub_row(app, t.bot_id).trial_messages_used == 5
        assert _cfg(anon, "alice").status_code == 404  # allowance used up
    warned = [m for m in mailer.sent if "80%" in m.subject]
    assert len(warned) == 1 and warned[0].to == t.email


# --- limits ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "plan,owner,expected",
    [(100, 50, 50), (100, 300, 100), (1000, None, 500), (None, 40, 40)],
)
def test_limits_are_min_of_plan_cap_owner(billing_app, plan, owner, expected):
    t = make_tenant(billing_app, "alice")
    _set_sub(billing_app, t.bot_id, status="active", plan_code="monthly")
    with billing_app.state.session_factory() as db:
        db.get(Plan, "monthly").limits = json.dumps({"daily_message_cap": plan} if plan else {})
        row = db.query(BotLimits).filter_by(bot_id=t.bot_id).one_or_none()
        if row is None:
            row = BotLimits(bot_id=t.bot_id)
            db.add(row)
        row.daily_message_cap = owner
        db.commit()
    assert t.client.get("/api/admin/limits").json()["daily_message_cap"] == expected


def test_plan_daily_cap_is_enforced_on_chat(billing_app):
    t = make_tenant(billing_app, "alice")
    _set_sub(billing_app, t.bot_id, status="active", plan_code="monthly")
    with billing_app.state.session_factory() as db:
        db.get(Plan, "monthly").limits = json.dumps({"daily_message_cap": 2})
        db.commit()
    with TestClient(billing_app) as anon:
        codes = [r.status_code for r in _chat(anon, "alice", 3)]
    assert codes == [200, 200, 429]


def test_purge_keeps_invoices_anonymised(billing_app):
    from mebot.models import Bot, Invoice

    t = make_tenant(billing_app, "alice")
    with billing_app.state.session_factory() as db:
        db.add(Invoice(bot_id=t.bot_id, provider="stripe", provider_invoice_id="in_1",
                       amount_minor=900, currency="USD", status="paid",
                       hosted_url="https://inv", pdf_url="https://pdf"))  # fmt: skip
        bot = db.get(Bot, t.bot_id)
        bot.status, bot.deletion_requested_at = "deleted", utcnow() - timedelta(days=30)
        db.commit()
    assert purge.purge_deleted(billing_app.state.session_factory, timedelta(days=7)) == 1
    with billing_app.state.session_factory() as db:
        inv = db.query(Invoice).one()
        assert (inv.amount_minor, inv.hosted_url, inv.pdf_url) == (900, None, None)
        assert db.query(Subscription).count() == 0


def test_legal_pages_hosted_only(hosted_app, client):
    with TestClient(hosted_app) as c:
        r = c.get("/legal/terms")
        assert r.status_code == 200 and "lawyer" in r.text
        assert c.get("/legal/privacy").status_code == 200
        assert c.get("/legal/secrets").status_code == 404
    assert client.get("/legal/terms").status_code == 404
