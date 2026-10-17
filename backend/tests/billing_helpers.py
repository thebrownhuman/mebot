"""Signed webhook requests for the billing tests (test-mode secrets from conftest)."""

import hashlib
import hmac
import itertools
import json
import time

from tests.conftest import BILLING_ENV

_ids = itertools.count(1)


def stripe_post(client, type_: str, obj: dict, *, created: int | None = None, event_id=None,
                secret: str | None = None):  # fmt: skip
    event = {
        "id": event_id or f"evt_test_{next(_ids)}",
        "type": type_,
        "created": created or int(time.time()),
        "data": {"object": obj},
    }
    body = json.dumps(event).encode()
    t = int(time.time())
    key = (secret or BILLING_ENV["stripe_webhook_secret"]).encode()
    sig = hmac.new(key, f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/billing/webhook/stripe",
        content=body,
        headers={"Stripe-Signature": f"t={t},v1={sig}", "Content-Type": "application/json"},
    )


def razorpay_post(client, event: str, sub: dict | None = None, *, invoice: dict | None = None,
                  created: int | None = None, event_id=None):  # fmt: skip
    payload = {}
    if sub is not None:
        payload["subscription"] = {"entity": sub}
    if invoice is not None:
        payload["invoice"] = {"entity": invoice}
    body = json.dumps(
        {"entity": "event", "event": event, "payload": payload,
         "created_at": created or int(time.time())}
    ).encode()  # fmt: skip
    sig = hmac.new(
        BILLING_ENV["razorpay_webhook_secret"].encode(), body, hashlib.sha256
    ).hexdigest()
    return client.post(
        "/api/billing/webhook/razorpay",
        content=body,
        headers={
            "X-Razorpay-Signature": sig,
            "X-Razorpay-Event-Id": event_id or f"evt_rzp_{next(_ids)}",
            "Content-Type": "application/json",
        },
    )


def sub_row(app, bot_id):
    from mebot.billing import service

    with app.state.session_factory() as db:
        sub = service.get_sub(db, bot_id)
        if sub is not None:
            db.expunge(sub)
        return sub
