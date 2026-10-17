"""Hosted mode, Account -> Billing for the logged-in owner (their own bot only).

Checkout and payment-method changes happen on the provider's hosted pages; no card or UPI
data reaches mebot. Starting a checkout changes no status: only the provider's webhook
does. 404 unless paid plans are on.
"""

import re
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mebot.billing import service, state
from mebot.config import Settings
from mebot.db import get_db
from mebot.deps import csrf_on_mutation, get_current_admin, get_current_bot, get_settings
from mebot.errors import ApiError
from mebot.models import Bot, Invoice, Plan, UsageCounter, utcnow
from mebot.routes.hosted_accounts import require_hosted

CURRENCY_PROVIDER = {"INR": "razorpay"}  # everything else: stripe


def require_billing(request: Request) -> None:
    if not service.enabled(request.app.state.settings):
        raise ApiError(404, "NOT_FOUND", "Not Found")


router = APIRouter(
    prefix="/api/hosted/billing",
    dependencies=[
        Depends(require_hosted),
        Depends(require_billing),
        Depends(get_current_admin),
        Depends(csrf_on_mutation),
    ],
)


class CheckoutReq(BaseModel):
    plan_code: str = Field(max_length=40)
    currency: str = Field(min_length=3, max_length=3)


class CancelReq(BaseModel):
    confirm: bool


GSTIN_RE = r"^[0-9]{2}[A-Z0-9]{10}[0-9A-Z]{3}$"


class GstinReq(BaseModel):
    gstin: str | None = Field(default=None, max_length=15)

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v):
        v = (v or "").strip().upper() or None
        if v is not None and not re.match(GSTIN_RE, v):
            raise ValueError("enter a 15-character GSTIN, e.g. 29ABCDE1234F1Z5")
        return v


def _offers(db: Session, settings: Settings) -> list[dict]:
    """Paid plans with a price in a currency whose provider is configured."""
    out = []
    for p in service.plans(db, active_only=True):
        if p.is_trial:
            continue
        prices = {}
        for cur, price in service.plan_view(p)["prices"].items():
            provider = price.get("provider")
            if provider in settings.billing_provider_list and price.get("provider_plan_id"):
                prices[cur] = {"amount_minor": int(price.get("amount_minor") or 0)}
        if prices:
            out.append({"code": p.code, "name": p.name, "prices": prices})
    return out


def _usage(db: Session, bot_id: str, since) -> dict:
    day = since.strftime("%Y-%m-%d")
    msgs, toks = db.execute(
        select(func.sum(UsageCounter.messages), func.sum(UsageCounter.tokens)).where(
            UsageCounter.bot_id == bot_id,
            UsageCounter.scope == "bot_day",
            UsageCounter.window_start >= day,
        )
    ).one()
    return {"since": since.isoformat(), "messages": int(msgs or 0), "tokens": int(toks or 0)}


def _iso(d):
    return d.isoformat() if d else None


def _view(db: Session, bot: Bot, settings: Settings) -> dict:
    now = utcnow()
    sub = service.get_sub(db, bot.id)
    status = sub.status if sub else "none"
    st = service.sub_state(sub) if sub else state.SubState("none")
    plan = db.get(Plan, sub.plan_code) if sub and sub.plan_code else None
    trial = None
    if sub and sub.trial_started_at:
        left = (sub.trial_ends_at - now) if sub.trial_ends_at else timedelta(0)
        trial = {
            "ends_at": _iso(sub.trial_ends_at),
            "days_left": -(-int(left.total_seconds()) // 86400) if left > timedelta(0) else 0,
            "messages_used": sub.trial_messages_used,
            "messages_total": settings.trial_messages,
        }
    if sub and sub.current_period_end and status in ("active", "past_due", "cancelled"):
        since = sub.current_period_end - timedelta(days=30)
    elif sub and sub.trial_started_at:
        since = sub.trial_started_at
    else:
        since = now - timedelta(days=30)
    serving_sub = status in ("active", "past_due", "cancelled") and state.serving(st, now)
    comp = sub.comp_until if sub and sub.comp_until and sub.comp_until > now else None
    manageable = bool(sub and (sub.provider_customer_id or sub.provider_subscription_id))
    return {
        "status": status,
        "serving": service.is_serving(db, settings, bot.id, now),
        "plan_code": sub.plan_code if sub else None,
        "plan_name": plan.name if plan else None,
        "provider": sub.provider if sub else None,
        "currency": sub.currency if sub else None,
        "current_period_end": _iso(sub.current_period_end) if sub else None,
        "cancel_at_period_end": bool(sub and sub.cancel_at_period_end),
        "grace_until": _iso(sub.grace_until) if sub else None,
        "comp_until": _iso(comp),
        "trial": trial,
        "usage": _usage(db, bot.id, since),
        "offers": _offers(db, settings),
        "providers": settings.billing_provider_list,
        "can_checkout": not serving_sub,
        "can_manage": manageable and bool(sub.provider),
        "can_cancel": status in ("active", "past_due") and bool(sub.provider_subscription_id),
        "platform_gstin": settings.platform_gstin,
        "owner_gstin": sub.owner_gstin if sub else None,
    }


def _base(request: Request, settings: Settings) -> str:
    return (settings.public_url or str(request.base_url)).rstrip("/")


def _limit(request: Request, bot_id: str) -> None:
    wait = request.app.state.checkout_limiter.hit(f"billing:{bot_id}")
    if wait is not None:
        raise ApiError(
            429, "RATE_LIMITED", "Too many attempts. Try again later.",
            headers={"Retry-After": str(wait)},
        )  # fmt: skip


@router.get("")
def billing(
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    settings: Settings = Depends(get_settings),
):
    return _view(db, bot, settings)


@router.get("/invoices")
def invoices(db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    rows = db.scalars(
        select(Invoice).where(Invoice.bot_id == bot.id).order_by(Invoice.created_at.desc())
    )
    return {
        "items": [
            {
                "id": i.id,
                "amount_minor": i.amount_minor,
                "currency": i.currency,
                "status": i.status,
                "period_start": _iso(i.period_start),
                "period_end": _iso(i.period_end),
                "created_at": _iso(i.created_at),
                "hosted_url": i.hosted_url,
                "pdf_url": i.pdf_url,
            }
            for i in rows
        ]
    }


@router.post("/checkout")
async def checkout(
    req: CheckoutReq,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    settings: Settings = Depends(get_settings),
    current=Depends(get_current_admin),
):
    """A hosted checkout URL. Nothing about the subscription changes until the webhook."""
    currency = req.currency.upper()
    plan = db.get(Plan, req.plan_code)
    if plan is None or not plan.active or plan.is_trial:
        raise ApiError(404, "PLAN_NOT_FOUND", "That plan isn't available.")
    price = service.price_for(plan, currency)
    expected = CURRENCY_PROVIDER.get(currency, "stripe")
    if (
        not price
        or price.get("provider") != expected
        or not price.get("provider_plan_id")
        or expected not in request.app.state.billing_providers
    ):
        raise ApiError(422, "CURRENCY_UNAVAILABLE", "That plan isn't sold in this currency.")
    sub = service.ensure_sub(db, bot.id)
    if sub.status in ("active", "past_due", "cancelled") and state.serving(
        service.sub_state(sub), utcnow()
    ):
        raise ApiError(409, "ALREADY_SUBSCRIBED", "You already have a subscription.")
    _limit(request, bot.id)
    provider = request.app.state.billing_providers[expected]
    base = _base(request, settings)
    url, remote_id = await provider.create_checkout(
        bot_id=bot.id,
        email=current.admin.email,
        plan_code=plan.code,
        provider_plan_id=price["provider_plan_id"],
        customer_id=sub.provider_customer_id if sub.provider == expected else None,
        success_url=f"{base}/admin/billing?checkout=done",
        cancel_url=f"{base}/admin/billing",
    )
    if remote_id:  # Razorpay: the subscription exists already; webhooks find it by id
        sub.provider, sub.provider_subscription_id = expected, remote_id
    db.commit()
    return {"url": url}


@router.post("/portal")
async def portal(
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    settings: Settings = Depends(get_settings),
):
    sub = service.get_sub(db, bot.id)
    provider = request.app.state.billing_providers.get((sub.provider if sub else None) or "")
    if sub is None or provider is None:
        raise ApiError(409, "NO_SUBSCRIPTION", "There's no subscription to manage yet.")
    _limit(request, bot.id)
    url = await provider.portal_url(
        customer_id=sub.provider_customer_id,
        subscription_id=sub.provider_subscription_id,
        return_url=f"{_base(request, settings)}/admin/billing",
    )
    return {"url": url}


@router.post("/cancel")
async def cancel(
    req: CancelReq,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    settings: Settings = Depends(get_settings),
):
    """Cancel at the end of the paid period (the bot keeps serving until then)."""
    if not req.confirm:
        raise ApiError(422, "CONFIRMATION_REQUIRED", "Please confirm the cancellation.")
    sub = service.get_sub(db, bot.id)
    if sub is None or sub.status not in ("active", "past_due") or not sub.provider_subscription_id:
        raise ApiError(409, "NOT_CANCELLABLE", "There's no active subscription to cancel.")
    provider = request.app.state.billing_providers.get(sub.provider or "")
    if provider is None:
        raise ApiError(409, "NOT_CANCELLABLE", "There's no active subscription to cancel.")
    _limit(request, bot.id)
    remote = await provider.cancel(sub.provider_subscription_id, at_period_end=True)
    # The provider confirmed (authenticated server-side call): record it now; Razorpay
    # sends no webhook until the period actually ends.
    new = state.transition(
        service.sub_state(sub), "cancel_at_end", utcnow(), period_end=remote.period_end
    )
    service.apply(db, sub, new, "owner cancelled")
    db.commit()
    return _view(db, bot, settings)


@router.put("/gstin")
def set_gstin(
    req: GstinReq,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    settings: Settings = Depends(get_settings),
):
    """Optional GSTIN for the owner's records / GST invoices (India)."""
    sub = service.ensure_sub(db, bot.id)
    sub.owner_gstin = req.gstin
    sub.updated_at = utcnow()
    db.commit()
    return _view(db, bot, settings)
