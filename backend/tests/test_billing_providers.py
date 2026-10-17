"""Provider adapters against respx (no real network)."""

import json
import logging
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from mebot.billing.providers import BillingError, Razorpay, Stripe

RZP = Razorpay("rzp_test_KEYID1234", "rzp_SECRET_abcdef", "rzp_whsec_x")
ST = Stripe("sk_test_SECRET_abcdef", "whsec_x")


@respx.mock
async def test_razorpay_checkout_creates_subscription_with_notes():
    route = respx.post("https://api.razorpay.com/v1/subscriptions").mock(
        return_value=httpx.Response(
            200, json={"id": "sub_R1", "short_url": "https://rzp.io/i/abc", "status": "created"}
        )
    )
    url, sub_id = await RZP.create_checkout(
        bot_id="b1", email="o@x.io", plan_code="monthly", provider_plan_id="plan_M",
        customer_id=None, success_url="s", cancel_url="c",
    )  # fmt: skip
    assert (url, sub_id) == ("https://rzp.io/i/abc", "sub_R1")
    sent = json.loads(route.calls[0].request.content)
    assert sent["plan_id"] == "plan_M" and sent["notes"] == {"bot_id": "b1", "plan_code": "monthly"}
    assert route.calls[0].request.headers["authorization"].startswith("Basic ")


@respx.mock
async def test_razorpay_cancel_and_fetch_map_statuses():
    respx.post("https://api.razorpay.com/v1/subscriptions/sub_R1/cancel").mock(
        return_value=httpx.Response(200, json={"id": "sub_R1", "status": "active", "current_end": 1800000000})
    )
    respx.get("https://api.razorpay.com/v1/subscriptions/sub_R1").mock(
        return_value=httpx.Response(200, json={"id": "sub_R1", "status": "halted", "current_end": 1800000000})
    )
    c = await RZP.cancel("sub_R1", at_period_end=True)
    assert c.status == "cancelled" and c.cancel_at_period_end and c.period_end.year == 2027
    assert (await RZP.fetch_subscription("sub_R1")).status == "past_due"


@respx.mock
async def test_stripe_checkout_form_and_portal():
    route = respx.post("https://api.stripe.com/v1/checkout/sessions").mock(
        return_value=httpx.Response(200, json={"id": "cs_1", "url": "https://checkout.stripe.com/c/1"})
    )
    portal = respx.post("https://api.stripe.com/v1/billing_portal/sessions").mock(
        return_value=httpx.Response(200, json={"url": "https://billing.stripe.com/p/1"})
    )
    url, sub_id = await ST.create_checkout(
        bot_id="b1", email="o@x.io", plan_code="monthly", provider_plan_id="price_1",
        customer_id=None, success_url="https://h/ok", cancel_url="https://h/no",
    )  # fmt: skip
    assert url == "https://checkout.stripe.com/c/1" and sub_id is None
    form = parse_qs(route.calls[0].request.content.decode())
    assert form["mode"] == ["subscription"] and form["line_items[0][price]"] == ["price_1"]
    assert form["client_reference_id"] == ["b1"] and form["customer_email"] == ["o@x.io"]
    assert form["subscription_data[metadata][bot_id]"] == ["b1"]
    assert route.calls[0].request.headers["authorization"] == "Bearer sk_test_SECRET_abcdef"
    assert await ST.portal_url(customer_id="cus_1", subscription_id=None, return_url="r") == (
        "https://billing.stripe.com/p/1"
    )
    assert parse_qs(portal.calls[0].request.content.decode())["customer"] == ["cus_1"]


@respx.mock
async def test_stripe_cancel_modes_and_fetch():
    respx.post("https://api.stripe.com/v1/subscriptions/sub_S1").mock(
        return_value=httpx.Response(
            200, json={"id": "sub_S1", "status": "active", "cancel_at_period_end": True,
                       "items": {"data": [{"current_period_end": 1800000000}]}},
        )  # fmt: skip
    )
    respx.delete("https://api.stripe.com/v1/subscriptions/sub_S1").mock(
        return_value=httpx.Response(200, json={"id": "sub_S1", "status": "canceled"})
    )
    at_end = await ST.cancel("sub_S1", at_period_end=True)
    assert at_end.status == "cancelled" and at_end.period_end.year == 2027
    assert (await ST.cancel("sub_S1", at_period_end=False)).status == "inactive"


@respx.mock
@pytest.mark.parametrize("provider,url,secrets", [
    (RZP, "https://api.razorpay.com/v1/subscriptions/sub_X",
     ("rzp_SECRET_abcdef", "rzp_test_KEYID1234")),
    (ST, "https://api.stripe.com/v1/subscriptions/sub_X", ("sk_test_SECRET_abcdef",)),
])  # fmt: skip
async def test_provider_errors_never_leak_secrets(provider, url, secrets, caplog):
    respx.get(url).mock(
        return_value=httpx.Response(
            401, text="bad key rzp_SECRET_abcdef sk_test_SECRET_abcdef rzp_test_KEYID1234"
        )
    )
    caplog.set_level(logging.DEBUG)
    with pytest.raises(BillingError) as e:
        await provider.fetch_subscription("sub_X")
    for secret in secrets:
        assert secret not in caplog.text and secret not in str(e.value.message)
    assert e.value.status == 502


@respx.mock
async def test_network_error_is_a_billing_error():
    respx.get("https://api.stripe.com/v1/subscriptions/sub_X").mock(
        side_effect=httpx.ConnectError("boom sk_test_SECRET_abcdef")
    )
    with pytest.raises(BillingError):
        await ST.fetch_subscription("sub_X")


def test_razorpay_parse_charged_and_invoice():
    ev = {
        "event": "subscription.charged", "created_at": 1760000000,
        "payload": {"subscription": {"entity": {
            "id": "sub_R1", "customer_id": "cust_1", "current_end": 1762600000,
            "notes": {"bot_id": "b1", "plan_code": "monthly"}}}},
    }  # fmt: skip
    n = RZP.parse(ev, {"x-razorpay-event-id": "evt_R1"})
    assert (n.event_id, n.action, n.bot_id, n.subscription_id) == ("evt_R1", "paid", "b1", "sub_R1")
    assert n.period_end.year == 2025 and n.occurred_at.year == 2025
    inv = RZP.parse({"event": "invoice.paid", "payload": {"invoice": {"entity": {
        "id": "inv_1", "subscription_id": "sub_R1", "amount_paid": 49900, "currency": "INR",
        "status": "paid", "short_url": "https://rzp.io/i/inv"}}}}, {}, b"{}")  # fmt: skip
    assert inv.invoice["amount_minor"] == 49900 and inv.event_id.startswith("sha256:")
    assert RZP.parse({"event": "payment.captured"}, {}, b"x").action is None


def test_stripe_parse_events():
    sub = {"id": "evt_1", "type": "customer.subscription.updated", "created": 1760000000,
           "data": {"object": {"id": "sub_S1", "customer": "cus_1", "status": "past_due",
                               "metadata": {"bot_id": "b1"}, "current_period_end": 1762600000}}}
    n = ST.parse(sub)
    assert (n.action, n.bot_id, n.subscription_id, n.customer_id) == ("failed", "b1", "sub_S1", "cus_1")
    done = ST.parse({"id": "evt_2", "type": "checkout.session.completed", "data": {"object": {
        "client_reference_id": "b1", "subscription": "sub_S1", "customer": "cus_1",
        "metadata": {"plan_code": "monthly"}, "currency": "usd"}}})  # fmt: skip
    assert (done.action, done.bot_id, done.plan_code, done.currency) == ("link", "b1", "monthly", "USD")
    inv = ST.parse({"id": "evt_3", "type": "invoice.paid", "data": {"object": {
        "id": "in_1", "amount_paid": 900, "currency": "usd", "status": "paid",
        "hosted_invoice_url": "https://inv", "invoice_pdf": "https://pdf",
        "parent": {"subscription_details": {"subscription": "sub_S1",
                                            "metadata": {"bot_id": "b1"}}}}}})  # fmt: skip
    assert inv.subscription_id == "sub_S1" and inv.invoice["pdf_url"] == "https://pdf"
    assert ST.parse({"id": "e", "type": "customer.subscription.deleted",
                     "data": {"object": {"id": "s"}}}).action == "cancel_now"  # fmt: skip
    assert ST.parse({"id": "e", "type": "charge.refunded", "data": {"object": {}}}).action is None
