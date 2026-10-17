"""Razorpay Subscriptions (INR; UPI AutoPay and cards).

Checkout = create a subscription and send the owner to its ``short_url``. Razorpay has no
customer portal: the same short_url updates the payment method, and cancelling goes
through our API.
"""

import hashlib
import json

from mebot.billing import signatures
from mebot.billing.providers.base import (
    BillingError,
    InvalidSignature,
    NormalizedEvent,
    RemoteSub,
    call,
    ts,
)

API = "https://api.razorpay.com/v1"
TOTAL_COUNT = 120  # monthly cycles one mandate covers (10 years); Razorpay needs a number

# Provider subscription status -> ours (created/authenticated: no opinion yet).
STATUS = {
    "active": "active",
    "pending": "past_due",
    "halted": "past_due",
    "cancelled": "inactive",
    "completed": "inactive",
    "expired": "inactive",
}
EVENT_ACTION = {
    "subscription.authenticated": "link",
    "subscription.activated": "paid",
    "subscription.charged": "paid",
    "subscription.resumed": "paid",
    "subscription.pending": "failed",
    "subscription.halted": "failed",
    "subscription.cancelled": "cancel_now",
    "subscription.completed": "cancel_now",
    "invoice.paid": "paid",
}


class Razorpay:
    name = "razorpay"
    currencies = ("INR",)
    reports_scheduled_cancel = False

    def __init__(self, key_id: str, key_secret: str, webhook_secret: str):
        self.key_id, self.key_secret, self.webhook_secret = key_id, key_secret, webhook_secret

    async def _call(self, method: str, path: str, **kw) -> dict:
        return await call(
            "razorpay", [self.key_id, self.key_secret, self.webhook_secret], method, API + path,
            auth=(self.key_id, self.key_secret), **kw,
        )  # fmt: skip

    async def create_checkout(
        self, *, bot_id, email, plan_code, provider_plan_id, customer_id, success_url,
        cancel_url,
    ):  # fmt: skip
        data = await self._call(
            "POST",
            "/subscriptions",
            json={
                "plan_id": provider_plan_id,
                "total_count": TOTAL_COUNT,
                "quantity": 1,
                "customer_notify": 1,
                "notes": {"bot_id": bot_id, "plan_code": plan_code},
            },
        )
        if not data.get("short_url") or not data.get("id"):
            raise BillingError()
        return data["short_url"], data["id"]

    async def portal_url(self, *, customer_id, subscription_id, return_url):
        if not subscription_id:
            raise BillingError("There's no subscription to manage yet.")
        data = await self._call("GET", f"/subscriptions/{subscription_id}")
        if not data.get("short_url"):
            raise BillingError()
        return data["short_url"]

    @staticmethod
    def _remote(data: dict) -> RemoteSub:
        return RemoteSub(
            status=STATUS.get(data.get("status") or ""),
            period_end=ts(data.get("current_end")),
            customer_id=data.get("customer_id"),
        )

    async def cancel(self, subscription_id: str, at_period_end: bool) -> RemoteSub:
        data = await self._call(
            "POST",
            f"/subscriptions/{subscription_id}/cancel",
            json={"cancel_at_cycle_end": 1 if at_period_end else 0},
        )
        remote = self._remote(data)
        if at_period_end:  # stays "active" at Razorpay until the cycle ends
            remote.status, remote.cancel_at_period_end = "cancelled", True
        return remote

    async def fetch_subscription(self, subscription_id: str) -> RemoteSub:
        return self._remote(await self._call("GET", f"/subscriptions/{subscription_id}"))

    def verify_webhook(self, headers, raw_body: bytes) -> dict:
        if not signatures.razorpay_valid(
            self.webhook_secret, raw_body, headers.get("x-razorpay-signature")
        ):
            raise InvalidSignature()
        return json.loads(raw_body)

    def parse(self, event: dict, headers=None, raw_body: bytes = b"") -> NormalizedEvent:
        etype = str(event.get("event") or "unknown")
        event_id = (headers or {}).get("x-razorpay-event-id") or (
            "sha256:" + hashlib.sha256(raw_body).hexdigest()
        )
        payload = event.get("payload") or {}
        sub = (payload.get("subscription") or {}).get("entity") or {}
        inv = (payload.get("invoice") or {}).get("entity") or {}
        notes = sub.get("notes") or inv.get("notes") or {}
        if not isinstance(notes, dict):  # Razorpay sends [] for empty notes
            notes = {}
        out = NormalizedEvent(
            provider="razorpay",
            event_id=event_id,
            type=etype,
            occurred_at=ts(event.get("created_at")),
            action=EVENT_ACTION.get(etype),
            bot_id=notes.get("bot_id"),
            plan_code=notes.get("plan_code"),
            subscription_id=sub.get("id") or inv.get("subscription_id"),
            customer_id=sub.get("customer_id") or inv.get("customer_id"),
            period_end=ts(sub.get("current_end")),
            currency="INR",
            raw=event,
        )
        if inv.get("id"):
            out.invoice = {
                "provider_invoice_id": inv["id"],
                "amount_minor": int(inv.get("amount_paid") or inv.get("amount") or 0),
                "currency": str(inv.get("currency") or "INR").upper(),
                "status": inv.get("status") or "paid",
                "period_start": ts(inv.get("billing_start")),
                "period_end": ts(inv.get("billing_end")),
                "hosted_url": inv.get("short_url"),
                "pdf_url": None,
                "tax_minor": inv.get("tax_amount"),
            }
        return out
