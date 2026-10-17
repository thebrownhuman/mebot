"""Billing providers: Razorpay (INR) and Stripe. Raw httpx, no SDKs."""

from mebot.billing.providers.base import (
    BillingError,
    BillingProvider,
    InvalidSignature,
    NormalizedEvent,
    RemoteSub,
)
from mebot.billing.providers.razorpay import Razorpay
from mebot.billing.providers.stripe import Stripe

__all__ = [
    "BillingError", "BillingProvider", "InvalidSignature", "NormalizedEvent", "RemoteSub",
    "Razorpay", "Stripe", "make",
]  # fmt: skip


def make(name: str, settings) -> BillingProvider:
    if name == "razorpay":
        return Razorpay(
            settings.razorpay_key_id, settings.razorpay_key_secret,
            settings.razorpay_webhook_secret,
        )  # fmt: skip
    if name == "stripe":
        return Stripe(settings.stripe_secret_key, settings.stripe_webhook_secret)
    raise KeyError(name)
