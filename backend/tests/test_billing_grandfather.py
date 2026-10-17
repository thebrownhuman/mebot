"""Bots that were live before paid plans were switched on get a fresh trial, not an outage."""

from datetime import timedelta

from fastapi.testclient import TestClient

from mebot.billing import jobs, service
from mebot.hosted.mailer import ConsoleMailer
from mebot.models import Subscription, TrialClaim, utcnow
from tests.billing_helpers import sub_row
from tests.conftest import HOSTED_SECRET, make_tenant


def _claims(app):
    with app.state.session_factory() as db:
        return {c.email_hash for c in db.query(TrialClaim)}


def test_pre_billing_bot_serves_and_gets_a_trial_on_first_request(billing_app):
    t = make_tenant(billing_app, "alice")
    assert sub_row(billing_app, t.bot_id) is None  # existed before billing: no row
    with TestClient(billing_app) as anon:
        assert anon.get("/b/alice/api/public/config").status_code == 200
    sub = sub_row(billing_app, t.bot_id)
    assert sub.status == "trialing" and sub.plan_code == "trial"
    assert timedelta(days=13) < sub.trial_ends_at - utcnow() <= timedelta(days=14)
    assert sub.trial_messages_used == 0
    assert service.email_hash(HOSTED_SECRET, t.email) in _claims(billing_app)
    t.client.__exit__(None, None, None)


def test_grandfathering_is_idempotent(billing_app):
    t = make_tenant(billing_app, "alice")
    with billing_app.state.session_factory() as db:
        for _ in range(3):
            assert service.is_serving(db, billing_app.state.settings, t.bot_id)
    with billing_app.state.session_factory() as db:
        assert db.query(Subscription).filter_by(bot_id=t.bot_id).count() == 1
    t.client.__exit__(None, None, None)


def test_grandfathered_even_if_email_had_a_trial_before(billing_app):
    t = make_tenant(billing_app, "alice")
    with billing_app.state.session_factory() as db:
        db.add(TrialClaim(email_hash=service.email_hash(HOSTED_SECRET, t.email)))
        db.commit()
    with TestClient(billing_app) as anon:
        assert anon.get("/b/alice/api/public/config").status_code == 200
    assert sub_row(billing_app, t.bot_id).status == "trialing"
    t.client.__exit__(None, None, None)


async def test_sweep_grandfathers_live_bots_only_and_sends_trial_mails(billing_app):
    billing_app.state.mailer = mailer = ConsoleMailer()
    live = make_tenant(billing_app, "alice")
    unverified = make_tenant(billing_app, "bobby", verified=False)
    await jobs.run_sweep(billing_app)
    assert sub_row(billing_app, live.bot_id).status == "trialing"
    assert sub_row(billing_app, unverified.bot_id) is None
    await jobs.run_sweep(billing_app, now=utcnow() + timedelta(days=12))
    await jobs.run_sweep(billing_app, now=utcnow() + timedelta(days=15))
    assert sub_row(billing_app, live.bot_id).status == "inactive"
    assert [m.subject for m in mailer.sent] == [
        "Your mebot trial ends in 3 days",
        "Your mebot trial has ended",
    ]
    for t in (live, unverified):
        t.client.__exit__(None, None, None)


def test_new_signup_with_used_email_still_gets_no_trial(billing_app, monkeypatch):
    async def ok(secret, token, ip):
        return True

    monkeypatch.setattr("mebot.turnstile.verify", ok)
    billing_app.state.mailer = ConsoleMailer()
    with billing_app.state.session_factory() as db:
        db.add(TrialClaim(email_hash=service.email_hash(HOSTED_SECRET, "used@example.com")))
        db.commit()
    from tests.conftest import ADMIN_PASSWORD, csrf

    with TestClient(billing_app) as c:
        body = {
            "email": "used@example.com", "password": ADMIN_PASSWORD, "bot_name": "U",
            "slug": "used-one", "turnstile_token": "good", "accept_terms": True,
        }  # fmt: skip
        assert c.post("/api/hosted/signup", json=body, headers=csrf(c)).status_code == 202
    with billing_app.state.session_factory() as db:
        from mebot.models import Admin

        bot_id = db.query(Admin).filter_by(email="used@example.com").one().bot_id
        assert service.get_sub(db, bot_id).status == "none"
        assert not service.is_serving(db, billing_app.state.settings, bot_id)


def test_billing_off_creates_no_rows(hosted_app):
    t = make_tenant(hosted_app, "alice")
    with TestClient(hosted_app) as anon:
        assert anon.get("/b/alice/api/public/config").status_code == 200
    assert sub_row(hosted_app, t.bot_id) is None
    t.client.__exit__(None, None, None)
