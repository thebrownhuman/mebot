"""Stripe (USD and other currencies): Checkout Session in subscription mode + Billing Portal.

Requests are form-encoded with bracketed keys (Stripe's API format); no SDK.
"""

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

API = "https://api.stripe.com/v1"

STATUS = {
    "active": "active",
    "trialing": "active",
    "past_due": "past_due",
    "unpaid": "past_due",
    "canceled": "inactive",
    "incomplete_expired": "inactive",
    "paused": "inactive",
}


def _period_end(obj: dict):
    end = obj.get("current_period_end")
    if end is None:  # newer API versions keep it on the items
        items = (obj.get("items") or {}).get("data") or []
        end = items[0].get("current_period_end") if items else None
    return ts(end)


def _sub_action(obj: dict) -> str | None:
    status = obj.get("status")
    if status in ("active", "trialing"):
        return "cancel_at_end" if obj.get("cancel_at_period_end") else "paid"
    if status in ("past_due", "unpaid"):
        return "failed"
    if status in ("canceled", "incomplete_expired", "paused"):
        return "cancel_now"
    return "link"  # incomplete: no payment yet


class Stripe:
    name = "stripe"
    currencies = ("USD", "EUR", "GBP")
    reports_scheduled_cancel = True

    def __init__(self, secret_key: str, webhook_secret: str):
        self.secret_key, self.webhook_secret = secret_key, webhook_secret

    async def _call(self, method: str, path: str, data: dict | None = None) -> dict:
        return await call(
            "stripe", [self.secret_key, self.webhook_secret], method, API + path,
            headers={"Authorization": f"Bearer {self.secret_key}"}, data=data,
        )  # fmt: skip

    async def create_checkout(
        self, *, bot_id, email, plan_code, provider_plan_id, customer_id, success_url,
        cancel_url,
    ):  # fmt: skip
        form = {
            "mode": "subscription",
            "line_items[0][price]": provider_plan_id,
            "line_items[0][quantity]": "1",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": bot_id,
            "metadata[bot_id]": bot_id,
            "metadata[plan_code]": plan_code,
            "subscription_data[metadata][bot_id]": bot_id,
            "subscription_data[metadata][plan_code]": plan_code,
        }
        if customer_id:
            form["customer"] = customer_id
        else:
            form["customer_email"] = email
        data = await self._call("POST", "/checkout/sessions", form)
        if not data.get("url"):
            raise BillingError()
        return data["url"], None  # the subscription exists only after payment

    async def portal_url(self, *, customer_id, subscription_id, return_url):
        if not customer_id:
            raise BillingError("There's no subscription to manage yet.")
        data = await self._call(
            "POST", "/billing_portal/sessions", {"customer": customer_id, "return_url": return_url}
        )
        if not data.get("url"):
            raise BillingError()
        return data["url"]

    @staticmethod
    def _remote(obj: dict) -> RemoteSub:
        status = STATUS.get(obj.get("status") or "")
        at_end = bool(obj.get("cancel_at_period_end"))
        if status == "active" and at_end:
            status = "cancelled"
        return RemoteSub(
            status=status, period_end=_period_end(obj), cancel_at_period_end=at_end,
            customer_id=obj.get("customer"),
        )  # fmt: skip

    async def cancel(self, subscription_id: str, at_period_end: bool) -> RemoteSub:
        if at_period_end:
            obj = await self._call(
                "POST", f"/subscriptions/{subscription_id}", {"cancel_at_period_end": "true"}
            )
        else:
            obj = await self._call("DELETE", f"/subscriptions/{subscription_id}")
        return self._remote(obj)

    async def fetch_subscription(self, subscription_id: str) -> RemoteSub:
        return self._remote(await self._call("GET", f"/subscriptions/{subscription_id}"))

    def verify_webhook(self, headers, raw_body: bytes) -> dict:
        if not signatures.stripe_valid(
            self.webhook_secret, raw_body, headers.get("stripe-signature")
        ):
            raise InvalidSignature()
        return json.loads(raw_body)

    def parse(self, event: dict, headers=None, raw_body: bytes = b"") -> NormalizedEvent:
        etype = str(event.get("type") or "unknown")
        obj = (event.get("data") or {}).get("object") or {}
        out = NormalizedEvent(
            provider="stripe",
            event_id=str(event.get("id") or ""),
            type=etype,
            occurred_at=ts(event.get("created")),
            raw=event,
        )
        if etype == "checkout.session.completed":
            meta = obj.get("metadata") or {}
            out.action = "link"
            out.bot_id = obj.get("client_reference_id") or meta.get("bot_id")
            out.plan_code = meta.get("plan_code")
            out.subscription_id = obj.get("subscription")
            out.customer_id = obj.get("customer")
            out.currency = (obj.get("currency") or "").upper() or None
        elif etype.startswith("customer.subscription."):
            meta = obj.get("metadata") or {}
            out.action = "cancel_now" if etype.endswith(".deleted") else _sub_action(obj)
            out.bot_id, out.plan_code = meta.get("bot_id"), meta.get("plan_code")
            out.subscription_id, out.customer_id = obj.get("id"), obj.get("customer")
            out.period_end = _period_end(obj)
            out.currency = (obj.get("currency") or "").upper() or None
        elif etype in ("invoice.paid", "invoice.payment_failed"):
            parent = (obj.get("parent") or {}).get("subscription_details") or {}
            legacy = obj.get("subscription_details") or {}
            meta = parent.get("metadata") or legacy.get("metadata") or {}
            sub = obj.get("subscription") or parent.get("subscription")
            out.action = "paid" if etype == "invoice.paid" else "failed"
            out.bot_id, out.plan_code = meta.get("bot_id"), meta.get("plan_code")
            out.subscription_id = sub if isinstance(sub, str) else (sub or {}).get("id")
            out.customer_id = obj.get("customer")
            out.currency = (obj.get("currency") or "").upper() or None
            if obj.get("id"):
                paid = etype == "invoice.paid"
                out.invoice = {
                    "provider_invoice_id": obj["id"],
                    "amount_minor": int(
                        (obj.get("amount_paid") if paid else obj.get("amount_due")) or 0
                    ),
                    "currency": out.currency or "USD",
                    "status": obj.get("status") or ("paid" if paid else "open"),
                    "period_start": ts(obj.get("period_start")),
                    "period_end": ts(obj.get("period_end")),
                    "hosted_url": obj.get("hosted_invoice_url"),
                    "pdf_url": obj.get("invoice_pdf"),
                    "tax_minor": obj.get("tax"),
                }
        return out
