"""Account -> Billing API, sweep/reconcile jobs and deletion cancelling the subscription."""

import json
from datetime import timedelta
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from mebot.billing import jobs, service
from mebot.hosted.mailer import ConsoleMailer
from mebot.models import Bot, Invoice, Plan, PlatformAudit, utcnow
from tests.billing_helpers import stripe_post, sub_row
from tests.conftest import ADMIN_PASSWORD, csrf, make_tenant

RZP = "https://api.razorpay.com/v1"
STRIPE = "https://api.stripe.com/v1"


@pytest.fixture
def priced(billing_app):
    with billing_app.state.session_factory() as db:
        db.get(Plan, "monthly").prices = json.dumps(
            {
                "INR": {
                    "amount_minor": 49900,
                    "provider": "razorpay",
                    "provider_plan_id": "plan_M",
                },
                "USD": {"amount_minor": 900, "provider": "stripe", "provider_plan_id": "price_M"},
            }
        )
        db.commit()
    return billing_app


@pytest.fixture
def alice(priced):
    t = make_tenant(priced, "alice")
    yield t
    t.client.__exit__(None, None, None)


def _set_sub(app, bot_id, **fields):
    with app.state.session_factory() as db:
        sub = service.ensure_sub(db, bot_id)
        for k, v in fields.items():
            setattr(sub, k, v)
        db.commit()


def test_billing_routes_404_without_billing(tenants):
    a, _ = tenants
    assert a.client.get("/api/hosted/billing").status_code == 404


def test_billing_routes_need_login(priced):
    with TestClient(priced) as anon:
        assert anon.get("/api/hosted/billing").status_code == 401


def test_view_shows_trial_offers_and_usage(alice, priced):
    _set_sub(
        priced, alice.bot_id, status="trialing", trial_started_at=utcnow(),
        trial_ends_at=utcnow() + timedelta(days=5, hours=1), trial_messages_used=12,
    )  # fmt: skip
    v = alice.client.get("/api/hosted/billing").json()
    assert v["status"] == "trialing" and v["serving"] and v["can_checkout"]
    assert v["trial"] == {
        "ends_at": v["trial"]["ends_at"], "days_left": 6, "messages_used": 12,
        "messages_total": 200,
    }  # fmt: skip
    assert v["offers"] == [
        {"code": "monthly", "name": "Monthly",
         "prices": {"INR": {"amount_minor": 49900}, "USD": {"amount_minor": 900}}}
    ]  # fmt: skip
    assert v["usage"]["messages"] == 0 and not v["can_cancel"]


@respx.mock
def test_checkout_razorpay_links_subscription_but_changes_no_status(alice, priced):
    respx.post(f"{RZP}/subscriptions").mock(
        return_value=httpx.Response(200, json={"id": "sub_R9", "short_url": "https://rzp.io/i/x"})
    )
    r = alice.client.post(
        "/api/hosted/billing/checkout", json={"plan_code": "monthly", "currency": "inr"},
        headers=csrf(alice.client),
    )  # fmt: skip
    assert r.status_code == 200 and r.json() == {"url": "https://rzp.io/i/x"}
    sub = sub_row(priced, alice.bot_id)
    assert sub.status == "none" and sub.provider_subscription_id == "sub_R9"


@respx.mock
def test_checkout_stripe_sends_success_url(alice, priced):
    route = respx.post(f"{STRIPE}/checkout/sessions").mock(
        return_value=httpx.Response(200, json={"url": "https://checkout.stripe.com/c/x"})
    )
    r = alice.client.post(
        "/api/hosted/billing/checkout", json={"plan_code": "monthly", "currency": "USD"},
        headers=csrf(alice.client),
    )  # fmt: skip
    assert r.json()["url"] == "https://checkout.stripe.com/c/x"
    form = parse_qs(route.calls[0].request.content.decode())
    assert form["success_url"] == ["https://mebot.example/admin/billing?checkout=done"]
    assert form["customer_email"] == [alice.email]


@pytest.mark.parametrize(
    "body,code",
    [
        ({"plan_code": "trial", "currency": "USD"}, "PLAN_NOT_FOUND"),
        ({"plan_code": "nope", "currency": "USD"}, "PLAN_NOT_FOUND"),
        ({"plan_code": "monthly", "currency": "EUR"}, "CURRENCY_UNAVAILABLE"),
    ],
)
def test_checkout_rejects_bad_plan_or_currency(alice, body, code):
    r = alice.client.post("/api/hosted/billing/checkout", json=body, headers=csrf(alice.client))
    assert r.json()["error"]["code"] == code


def test_checkout_refused_while_subscribed(alice, priced):
    _set_sub(priced, alice.bot_id, status="active", provider="stripe",
             provider_subscription_id="sub_S1")  # fmt: skip
    r = alice.client.post(
        "/api/hosted/billing/checkout", json={"plan_code": "monthly", "currency": "USD"},
        headers=csrf(alice.client),
    )  # fmt: skip
    assert r.status_code == 409


@respx.mock
def test_portal_stripe_and_razorpay(alice, priced):
    respx.post(f"{STRIPE}/billing_portal/sessions").mock(
        return_value=httpx.Response(200, json={"url": "https://billing.stripe.com/p/x"})
    )
    respx.get(f"{RZP}/subscriptions/sub_R1").mock(
        return_value=httpx.Response(200, json={"id": "sub_R1", "short_url": "https://rzp.io/i/u"})
    )
    assert (
        alice.client.post("/api/hosted/billing/portal", headers=csrf(alice.client)).status_code
        == 409
    )
    _set_sub(priced, alice.bot_id, status="active", provider="stripe", provider_customer_id="cus_1")
    r = alice.client.post("/api/hosted/billing/portal", headers=csrf(alice.client))
    assert r.json()["url"] == "https://billing.stripe.com/p/x"
    _set_sub(priced, alice.bot_id, provider="razorpay", provider_subscription_id="sub_R1")
    r = alice.client.post("/api/hosted/billing/portal", headers=csrf(alice.client))
    assert r.json()["url"] == "https://rzp.io/i/u"


@respx.mock
def test_cancel_at_period_end_keeps_serving(alice, priced):
    end = utcnow() + timedelta(days=10)
    _set_sub(priced, alice.bot_id, status="active", provider="razorpay",
             provider_subscription_id="sub_R1", current_period_end=end)  # fmt: skip
    route = respx.post(f"{RZP}/subscriptions/sub_R1/cancel").mock(
        return_value=httpx.Response(
            200, json={"id": "sub_R1", "status": "active", "current_end": int(end.timestamp())}
        )  # fmt: skip
    )
    c = alice.client
    assert c.post("/api/hosted/billing/cancel", json={"confirm": False},
                  headers=csrf(c)).status_code == 422  # fmt: skip
    r = c.post("/api/hosted/billing/cancel", json={"confirm": True}, headers=csrf(c))
    assert r.status_code == 200, r.text
    assert json.loads(route.calls[0].request.content) == {"cancel_at_cycle_end": 1}
    v = r.json()
    assert v["status"] == "cancelled" and v["cancel_at_period_end"] and v["serving"]
    with TestClient(priced) as anon:
        assert anon.get("/b/alice/api/public/config").status_code == 200


def test_invoices_list_only_own(alice, priced):
    other = make_tenant(priced, "bobby")
    with priced.state.session_factory() as db:
        for bot_id, inv in ((alice.bot_id, "in_A"), (other.bot_id, "in_ZQXB")):
            db.add(Invoice(bot_id=bot_id, provider="stripe", provider_invoice_id=inv,
                           amount_minor=900, currency="USD", status="paid"))  # fmt: skip
        db.commit()
    items = alice.client.get("/api/hosted/billing/invoices").json()["items"]
    assert [i["amount_minor"] for i in items] == [900]
    assert "in_ZQXB" not in alice.client.get("/api/hosted/billing/invoices").text
    other.client.__exit__(None, None, None)


# --- jobs ----------------------------------------------------------------------------------


async def test_sweep_expires_and_mails_once(alice, priced):
    priced.state.mailer = mailer = ConsoleMailer()
    _set_sub(priced, alice.bot_id, status="trialing", trial_started_at=utcnow(),
             trial_ends_at=utcnow() + timedelta(days=2))  # fmt: skip
    await jobs.run_sweep(priced)
    await jobs.run_sweep(priced)
    assert [m.subject for m in mailer.sent] == ["Your mebot trial ends in 3 days"]
    await jobs.run_sweep(priced, now=utcnow() + timedelta(days=3))
    assert sub_row(priced, alice.bot_id).status == "inactive"
    assert mailer.sent[-1].subject == "Your mebot trial has ended"
    await jobs.run_sweep(priced, now=utcnow() + timedelta(days=95))
    assert "offline for 90 days" in mailer.sent[-1].subject
    assert len(mailer.sent) == 3


async def test_sweep_grace_expiry(alice, priced):
    _set_sub(priced, alice.bot_id, status="past_due", grace_until=utcnow() + timedelta(days=1))
    await jobs.run_sweep(priced)
    assert sub_row(priced, alice.bot_id).status == "past_due"
    await jobs.run_sweep(priced, now=utcnow() + timedelta(days=2))
    assert sub_row(priced, alice.bot_id).status == "inactive"


@respx.mock
async def test_reconcile_fixes_drift_and_audits(alice, priced):
    other = make_tenant(priced, "bobby")
    _set_sub(priced, alice.bot_id, status="active", provider="stripe",
             provider_subscription_id="sub_S1")  # fmt: skip
    _set_sub(priced, other.bot_id, status="cancelled", provider="razorpay",
             provider_subscription_id="sub_R1", current_period_end=utcnow() + timedelta(days=3),
             cancel_at_period_end=True)  # fmt: skip
    respx.get(f"{STRIPE}/subscriptions/sub_S1").mock(
        return_value=httpx.Response(200, json={"id": "sub_S1", "status": "past_due"})
    )
    respx.get(f"{RZP}/subscriptions/sub_R1").mock(  # scheduled cancel still shows "active"
        return_value=httpx.Response(200, json={"id": "sub_R1", "status": "active"})
    )
    out = await jobs.reconcile(priced, actor_id="op1")
    assert out == {"checked": 2, "fixed": 1, "errors": 0}
    s = sub_row(priced, alice.bot_id)
    assert s.status == "past_due" and s.grace_until is not None
    assert sub_row(priced, other.bot_id).status == "cancelled"
    with priced.state.session_factory() as db:
        a = db.query(PlatformAudit).one()
        assert (a.action, a.detail, a.target_bot_id) == (
            "billing_drift_fixed",
            "active->past_due",
            alice.bot_id,
        )
    other.client.__exit__(None, None, None)


@respx.mock
async def test_reconcile_counts_provider_errors(alice, priced):
    _set_sub(priced, alice.bot_id, status="active", provider="stripe",
             provider_subscription_id="sub_S1")  # fmt: skip
    respx.get(f"{STRIPE}/subscriptions/sub_S1").mock(return_value=httpx.Response(500))
    assert (await jobs.reconcile(priced))["errors"] == 1
    assert sub_row(priced, alice.bot_id).status == "active"


# --- deletion --------------------------------------------------------------------------------


def _delete(c):
    return c.post("/api/hosted/account/delete", json={"password": ADMIN_PASSWORD}, headers=csrf(c))


@respx.mock
def test_delete_cancels_subscription_first(alice, priced):
    _set_sub(priced, alice.bot_id, status="active", provider="stripe",
             provider_subscription_id="sub_S1")  # fmt: skip
    route = respx.delete(f"{STRIPE}/subscriptions/sub_S1").mock(
        return_value=httpx.Response(200, json={"id": "sub_S1", "status": "canceled"})
    )
    assert _delete(alice.client).status_code == 204
    assert route.called
    assert sub_row(priced, alice.bot_id).status == "inactive"


@respx.mock
def test_delete_blocked_when_cancel_fails(alice, priced):
    _set_sub(priced, alice.bot_id, status="active", provider="stripe",
             provider_subscription_id="sub_S1")  # fmt: skip
    respx.delete(f"{STRIPE}/subscriptions/sub_S1").mock(return_value=httpx.Response(500))
    r = _delete(alice.client)
    assert r.status_code == 502 and r.json()["error"]["code"] == "BILLING_CANCEL_FAILED"
    with priced.state.session_factory() as db:
        assert db.get(Bot, alice.bot_id).status == "active"


def test_delete_without_subscription_needs_no_provider(alice, priced):
    assert _delete(alice.client).status_code == 204


def test_webhook_then_view_round_trip(alice, priced):
    with TestClient(priced) as anon:
        stripe_post(anon, "checkout.session.completed", {
            "client_reference_id": alice.bot_id, "subscription": "sub_S1", "customer": "cus_1",
            "currency": "usd", "metadata": {"plan_code": "monthly"}})  # fmt: skip
        stripe_post(anon, "customer.subscription.updated", {
            "id": "sub_S1", "customer": "cus_1", "status": "active", "currency": "usd",
            "current_period_end": int((utcnow() + timedelta(days=30)).timestamp())})  # fmt: skip
    v = alice.client.get("/api/hosted/billing").json()
    assert v["status"] == "active" and v["plan_name"] == "Monthly" and v["currency"] == "USD"
    assert v["can_cancel"] and v["can_manage"] and not v["can_checkout"]
