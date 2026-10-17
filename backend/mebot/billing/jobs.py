"""Async billing jobs: the time sweep, reconciliation, provider-side cancels.

Provider calls happen outside DB sessions; results are applied in short transactions.
"""

import asyncio
import logging

from sqlalchemy.orm import Session

from mebot.billing import mails, service, state
from mebot.billing.providers import BillingError
from mebot.errors import ApiError
from mebot.hosted import mailer
from mebot.hosted import operator as op
from mebot.models import Subscription, utcnow

log = logging.getLogger("mebot.billing")
SWEEP_EVERY = 3600
RECONCILE_EVERY = 24  # sweeps


async def run_sweep(app, now=None) -> service.SweepResult:
    settings = app.state.settings
    with app.state.session_factory() as db:
        res = service.sweep(db, settings, now)
    for to, key in res.mails:
        await mailer.deliver(app.state.mailer, mails.build(key, to, settings))
    return res


async def reconcile(app, actor_id: str = "system", now=None) -> dict:
    """Ask the provider about every non-terminal subscription; fix and audit drift."""
    settings = app.state.settings
    out = {"checked": 0, "fixed": 0, "errors": 0}
    if not service.enabled(settings):
        return out
    with app.state.session_factory() as db:
        todo = [(s.id, s.provider, s.provider_subscription_id) for s in service.to_reconcile(db)]
    for sub_id, provider_name, remote_id in todo:
        provider = app.state.billing_providers.get(provider_name or "")
        if provider is None:
            continue
        out["checked"] += 1
        try:
            remote = await provider.fetch_subscription(remote_id)
        except BillingError:
            out["errors"] += 1
            continue
        with app.state.session_factory() as db:
            sub = db.get(Subscription, sub_id)
            drift = service.reconcile_one(
                db, sub, remote, provider, now, grace_days=settings.billing_grace_days
            )
            if drift:
                out["fixed"] += 1
                op.audit(db, actor_id, "billing_drift_fixed", sub.bot_id, drift)
            db.commit()
    log.info("billing reconcile: %s", out)
    return out


async def cancel_now_for_deletion(app, db: Session, bot_id: str) -> None:
    """Account deletion: cancel the provider subscription first. Raises (blocking the
    delete) if the provider won't confirm."""
    if not service.enabled(app.state.settings):
        return
    sub = service.get_sub(db, bot_id)
    if sub is None or not sub.provider_subscription_id or sub.status in ("none", "inactive"):
        return
    provider = app.state.billing_providers.get(sub.provider or "")
    if provider is None:
        raise ApiError(
            502, "BILLING_CANCEL_FAILED",
            "Your subscription couldn't be cancelled, so the account wasn't deleted. "
            "Contact support.",
        )  # fmt: skip
    try:
        await provider.cancel(sub.provider_subscription_id, at_period_end=False)
    except BillingError:
        raise ApiError(
            502, "BILLING_CANCEL_FAILED",
            "We couldn't cancel your subscription with the payment provider, so your account "
            "wasn't deleted. Try again in a few minutes.",
        ) from None  # fmt: skip
    new = state.transition(service.sub_state(sub), "cancel_now", utcnow())
    service.apply(db, sub, new, "account deleted")


async def billing_loop(app) -> None:
    """Hourly sweep; reconciliation once a day."""
    n = 0
    while True:
        await asyncio.sleep(SWEEP_EVERY)
        try:
            await run_sweep(app)
            n += 1
            if n % RECONCILE_EVERY == 0:
                await reconcile(app)
        except Exception:  # a failed round must not stop the loop; retry next hour
            log.exception("billing job failed")
