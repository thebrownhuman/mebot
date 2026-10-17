"""What every billing provider offers, and the provider-neutral event shape."""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

import httpx

from mebot.errors import ApiError
from mebot.llm.base import scrub

log = logging.getLogger("mebot.billing")
TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class InvalidSignature(Exception):
    pass


class BillingError(ApiError):
    """Provider call failed. The message never carries keys or the provider's raw body."""

    def __init__(self, message: str = "The payment provider didn't respond. Try again."):
        super().__init__(502, "BILLING_PROVIDER_ERROR", message)


@dataclass
class RemoteSub:
    """A subscription as the provider sees it, mapped to our statuses (None = no opinion,
    e.g. created but not yet authorised)."""

    status: str | None
    period_end: datetime | None = None
    cancel_at_period_end: bool = False
    customer_id: str | None = None


@dataclass
class NormalizedEvent:
    provider: str
    event_id: str
    type: str
    occurred_at: datetime | None
    # link | paid | failed | cancel_at_end | resume | cancel_now | None (store only)
    action: str | None = None
    bot_id: str | None = None
    plan_code: str | None = None
    subscription_id: str | None = None
    customer_id: str | None = None
    period_end: datetime | None = None
    currency: str | None = None
    invoice: dict | None = None
    raw: dict = field(default_factory=dict)


class BillingProvider(Protocol):
    name: str
    currencies: tuple[str, ...]
    # Does fetch_subscription show a cancel scheduled for the period end? (Razorpay: no.)
    reports_scheduled_cancel: bool

    async def create_checkout(
        self, *, bot_id: str, email: str, plan_code: str, provider_plan_id: str,
        customer_id: str | None, success_url: str, cancel_url: str,
    ) -> tuple[str, str | None]:  # fmt: skip
        """(hosted checkout url, provider subscription id if already known)."""

    async def portal_url(
        self, *, customer_id: str | None, subscription_id: str | None, return_url: str
    ) -> str: ...

    async def cancel(self, subscription_id: str, at_period_end: bool) -> RemoteSub: ...

    async def fetch_subscription(self, subscription_id: str) -> RemoteSub: ...

    def verify_webhook(self, headers, raw_body: bytes) -> dict: ...

    def parse(self, event: dict, headers=None, raw_body: bytes = b"") -> NormalizedEvent: ...


def ts(value) -> datetime | None:
    if value in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(int(value), UTC)
    except (TypeError, ValueError, OverflowError):
        return None


async def call(name: str, secrets: list[str | None], method: str, url: str, **kw) -> dict:
    """One provider request; failures are logged scrubbed and raised as BillingError."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.request(method, url, **kw)
    except httpx.HTTPError as e:
        log.warning("%s %s failed: %s", name, method, scrub(str(e), secrets))
        raise BillingError() from None
    if r.status_code >= 400:
        log.warning(
            "%s %s %s -> %d: %s", name, method, scrub(url, secrets), r.status_code,
            scrub(r.text[:300], secrets),
        )  # fmt: skip
        raise BillingError()
    try:
        return r.json()
    except ValueError:
        raise BillingError() from None
