"""POST /api/billing/webhook/{provider}: signatures, idempotency, ordering, errors."""

import logging
import time

import pytest
from fastapi.testclient import TestClient

from mebot.billing import service
from mebot.hosted import operator
from mebot.models import BillingEvent, Invoice
from tests.billing_helpers import razorpay_post, stripe_post, sub_row
from tests.conftest import make_tenant


@pytest.fixture
def pings(monkeypatch):
    sent = []

    async def fake(settings, text):
        sent.append(text)

    monkeypatch.setattr(operator, "ping", fake)
    return sent


@pytest.fixture
def env(billing_app, pings):
    t = make_tenant(billing_app, "alice")
    anon = TestClient(billing_app)
    anon.__enter__()
    yield billing_app, t, anon
    anon.__exit__(None, None, None)
    t.client.__exit__(None, None, None)


def _events(app):
    with app.state.session_factory() as db:
        return db.query(BillingEvent).order_by(BillingEvent.received_at).all()


def _stripe_activate(anon, bot_id, created=None):
    stripe_post(
        anon,
        "checkout.session.completed",
        {
            "client_reference_id": bot_id, "subscription": "sub_S1", "customer": "cus_1",
            "currency": "usd", "metadata": {"plan_code": "monthly"},
        },
        created=created,
    )  # fmt: skip
    return stripe_post(
        anon,
        "invoice.paid",
        {
            "id": "in_1", "amount_paid": 900, "currency": "usd", "status": "paid",
            "subscription": "sub_S1", "customer": "cus_1",
            "period_end": int(time.time()) + 86400 * 30,
            "hosted_invoice_url": "https://pay.stripe.com/i/1",
        },
        created=created,
    )  # fmt: skip


def test_404_when_billing_off(hosted_app, client):
    with TestClient(hosted_app) as c:
        assert c.post("/api/billing/webhook/stripe", content=b"{}").status_code == 404
    assert client.post("/api/billing/webhook/stripe", content=b"{}").status_code == 404


def test_unknown_provider_404(env):
    _, _, anon = env
    assert anon.post("/api/billing/webhook/paypal", content=b"{}").status_code == 404


def test_bad_signature_400_logged_without_body(env, caplog):
    app, t, anon = env
    caplog.set_level(logging.DEBUG)
    r = stripe_post(anon, "invoice.paid", {"id": "in_ZQXBODY"}, secret="whsec_wrong")
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_SIGNATURE"
    r = anon.post(
        "/api/billing/webhook/razorpay",
        content=b'{"x":"ZQXBODY"}',
        headers={"X-Razorpay-Signature": "00"},
    )
    assert r.status_code == 400
    assert "ZQXBODY" not in caplog.text and "invalid signature" in caplog.text
    assert _events(app) == []


def test_stripe_checkout_then_invoice_activates_and_stores_invoice(env, pings):
    app, t, anon = env
    assert _stripe_activate(anon, t.bot_id).status_code == 200
    sub = sub_row(app, t.bot_id)
    assert sub.status == "active" and sub.provider == "stripe"
    assert (sub.provider_subscription_id, sub.provider_customer_id) == ("sub_S1", "cus_1")
    assert sub.plan_code == "monthly" and sub.currency == "USD"
    with app.state.session_factory() as db:
        inv = db.query(Invoice).one()
    assert (inv.bot_id, inv.amount_minor, inv.currency) == (t.bot_id, 900, "USD")
    assert any("new subscription alice" in p for p in pings)
    assert all(e.processed_at and e.error is None for e in _events(app))


def _failed(anon, event_id):
    return stripe_post(
        anon,
        "invoice.payment_failed",
        {"id": "in_2", "subscription": "sub_S1", "amount_due": 900, "currency": "usd"},
        event_id=event_id,
    )


def test_duplicate_event_is_a_noop(env):
    app, t, anon = env
    _stripe_activate(anon, t.bot_id)
    r1 = _failed(anon, "evt_dup")
    first = sub_row(app, t.bot_id)
    assert r1.status_code == 200 and first.status == "past_due"
    r2 = _failed(anon, "evt_dup")
    assert r2.status_code == 200 and r2.json()["duplicate"] is True
    assert sub_row(app, t.bot_id).grace_until == first.grace_until
    assert [e.event_id for e in _events(app)].count("evt_dup") == 1


def test_out_of_order_old_event_does_not_change_status(env):
    app, t, anon = env
    now = int(time.time())
    _stripe_activate(anon, t.bot_id, created=now - 100)
    stripe_post(
        anon, "customer.subscription.deleted", {"id": "sub_S1", "status": "canceled"}, created=now
    )
    assert sub_row(app, t.bot_id).status == "inactive"
    # A late invoice.paid from before the cancellation: invoice upserted, status unchanged.
    r = stripe_post(
        anon,
        "invoice.paid",
        {"id": "in_late", "amount_paid": 900, "currency": "usd", "status": "paid",
         "subscription": "sub_S1"},
        created=now - 50,
    )  # fmt: skip
    assert r.status_code == 200
    assert sub_row(app, t.bot_id).status == "inactive"
    with app.state.session_factory() as db:
        assert db.query(Invoice).filter_by(provider_invoice_id="in_late").count() == 1
    assert _events(app)[-1].error == "stale"


def test_unknown_type_stored_and_200(env):
    app, _, anon = env
    r = stripe_post(anon, "charge.refunded", {"id": "ch_1", "billing_details": {"email": "x@y.z"}})
    assert r.status_code == 200
    ev = _events(app)[-1]
    assert ev.type == "charge.refunded" and ev.processed_at is not None
    assert "x@y.z" not in ev.payload  # PII stripped from the stored payload


def test_unmatched_event_is_noted_not_retried(env):
    app, _, anon = env
    r = stripe_post(anon, "invoice.paid", {"id": "in_9", "subscription": "sub_other"})
    assert r.status_code == 200 and _events(app)[-1].error == "unmatched"


def test_processing_error_500_recorded_pinged_then_retry_succeeds(env, monkeypatch, pings, caplog):
    app, t, anon = env
    real = service.handle_event
    body = {"client_reference_id": t.bot_id, "subscription": "sub_S1", "customer": "cus_1"}

    def boom(*a, **k):
        raise RuntimeError("db exploded near sk_test_SECRET_0000")

    monkeypatch.setattr(service, "handle_event", boom)
    caplog.set_level(logging.DEBUG)
    r = stripe_post(anon, "checkout.session.completed", body, event_id="evt_err")
    assert r.status_code == 500
    ev = _events(app)[-1]
    assert ev.processed_at is None and "RuntimeError" in ev.error
    assert "sk_test_SECRET_0000" not in ev.error and "sk_test_SECRET_0000" not in caplog.text
    assert any("billing webhook failed" in p for p in pings)
    monkeypatch.setattr(service, "handle_event", real)
    r = stripe_post(anon, "checkout.session.completed", body, event_id="evt_err")
    assert r.status_code == 200 and "duplicate" not in r.json()
    ev = _events(app)[-1]
    assert ev.processed_at is not None and ev.error is None
    assert sub_row(app, t.bot_id).provider_subscription_id == "sub_S1"


def test_razorpay_lifecycle(env, pings):
    app, t, anon = env
    end = int(time.time()) + 86400 * 30
    base = {
        "id": "sub_R1", "customer_id": "cust_1", "current_end": end,
        "notes": {"bot_id": t.bot_id, "plan_code": "monthly"},
    }  # fmt: skip
    now = int(time.time())
    razorpay_post(anon, "subscription.authenticated", base, created=now - 50)
    assert sub_row(app, t.bot_id).status == "none"
    razorpay_post(anon, "subscription.activated", base, created=now - 40)
    s = sub_row(app, t.bot_id)
    assert s.status == "active" and s.currency == "INR" and s.current_period_end.year >= 2026
    razorpay_post(anon, "subscription.pending", base, created=now - 30)
    s = sub_row(app, t.bot_id)
    assert s.status == "past_due" and s.grace_until is not None
    assert any("payment failed" in p for p in pings)
    razorpay_post(anon, "subscription.charged", base, created=now - 20)
    assert sub_row(app, t.bot_id).status == "active"
    razorpay_post(
        anon,
        "invoice.paid",
        invoice={"id": "inv_R1", "subscription_id": "sub_R1", "amount_paid": 49900,
                 "currency": "INR", "status": "paid"},
        created=now - 15,
    )  # fmt: skip
    razorpay_post(anon, "subscription.cancelled", base, created=now - 10)
    assert sub_row(app, t.bot_id).status == "inactive"
    assert any("cancelled alice" in p for p in pings)
    with app.state.session_factory() as db:
        assert db.query(Invoice).one().amount_minor == 49900


def test_events_for_a_replaced_subscription_do_not_touch_status(env):
    app, t, anon = env
    _stripe_activate(anon, t.bot_id)
    r = stripe_post(
        anon,
        "customer.subscription.deleted",
        {"id": "sub_OLD", "status": "canceled", "metadata": {"bot_id": t.bot_id}},
    )
    assert r.status_code == 200
    assert sub_row(app, t.bot_id).status == "active"
