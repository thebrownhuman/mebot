"""Billing logic over the DB: serving check, plan limits, trial, webhook events, sweep,
reconciliation and comps. Every function is a no-op (or "serving") when billing is off,
so self-hosted and billing-less hosted installs behave exactly as before.

Status changes come only from verified webhooks (handle_event), the provider's own answer
to a server-side call (cancel, reconcile) and the time sweep. Never from a redirect or a
client request.
"""

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from mebot.billing import state
from mebot.billing.providers import NormalizedEvent, RemoteSub
from mebot.models import Admin, Bot, Invoice, Plan, Subscription, TrialClaim, utcnow
from mebot.repos import logs

log = logging.getLogger("mebot.billing")

# Limit keys a plan may set: BotLimits fields plus imports per day.
LIMIT_KEYS = (
    "daily_message_cap", "daily_token_cap", "per_session_messages", "per_ip_per_day",
    "imports_per_day",
)  # fmt: skip
INACTIVE_REMINDER = timedelta(days=90)
TRIAL_WARN = timedelta(days=3)
PAYLOAD_KEEP = timedelta(days=30)
# Keys dropped from stored webhook payloads (PII the provider sends along).
PII_KEYS = {
    "email", "contact", "phone", "name", "address", "customer_email", "customer_name",
    "customer_phone", "customer_address", "customer_details", "billing_details", "shipping",
    "shipping_details", "receipt_email", "vpa", "card", "bank", "wallet", "notes_key",
}  # fmt: skip


def enabled(settings) -> bool:
    return bool(settings.billing_enabled)


# --- subscriptions -------------------------------------------------------------------


def get_sub(db: Session, bot_id: str) -> Subscription | None:
    return db.scalar(select(Subscription).where(Subscription.bot_id == bot_id))


def ensure_sub(db: Session, bot_id: str) -> Subscription:
    sub = get_sub(db, bot_id)
    if sub is None:
        sub = Subscription(bot_id=bot_id, status="none")
        db.add(sub)
        db.flush()
    return sub


def sub_state(sub: Subscription) -> state.SubState:
    return state.SubState(
        status=sub.status,
        grace_until=sub.grace_until,
        current_period_end=sub.current_period_end,
        cancel_at_period_end=sub.cancel_at_period_end,
        trial_ends_at=sub.trial_ends_at,
        trial_messages_used=sub.trial_messages_used,
        comp_until=sub.comp_until,
    )


def apply(db: Session, sub: Subscription, new: state.SubState, reason: str, now=None) -> bool:
    """Write a new state; log the transition. True if the status changed."""
    now = now or utcnow()
    old = sub.status
    sub.status = new.status
    sub.grace_until = new.grace_until
    sub.current_period_end = new.current_period_end
    sub.cancel_at_period_end = new.cancel_at_period_end
    sub.updated_at = now
    if old == new.status:
        return False
    sub.inactive_since = now if new.status == "inactive" else None
    logs.add(db, sub.bot_id, None, "billing_status", detail=f"{old}->{new.status} ({reason})")
    log.info("billing %s: %s -> %s (%s)", sub.bot_id, old, new.status, reason)
    return True


def is_serving(db: Session, settings, bot_id: str, now: datetime | None = None) -> bool:
    if not enabled(settings):
        return True
    sub = get_sub(db, bot_id)
    if sub is None:
        sub = grandfather(db, settings, bot_id, now)
        if sub is None:
            return False
    return state.serving(sub_state(sub), now or utcnow(), settings.trial_messages)


def grandfather(db: Session, settings, bot_id: str, now=None) -> Subscription | None:
    """A live bot with no subscription row existed before paid plans were switched on
    (sign-ups get their row at activation): give it a fresh trial from now instead of
    taking it offline, and claim the owner's e-mail so it can't start another one.

    Written in its own short transaction (callers may be read-only); a concurrent
    request inserting the same row first is fine (unique bot_id)."""
    from sqlalchemy.exc import IntegrityError

    from mebot.repos import bots

    if not enabled(settings) or bots.get_live_by_slug_id(db, bot_id) is None:
        return None
    now = now or utcnow()
    with Session(bind=db.get_bind()) as w:
        try:
            if get_sub(w, bot_id) is None:
                sub = Subscription(
                    bot_id=bot_id, status="none", plan_code="trial", trial_started_at=now,
                    trial_ends_at=now + timedelta(days=settings.trial_days),
                )  # fmt: skip
                w.add(sub)
                w.flush()
                apply(
                    w,
                    sub,
                    state.transition(sub_state(sub), "trial_start", now),
                    "grandfathered",
                    now,
                )
                email = owner_email(w, bot_id)
                if email and settings.secret_key:
                    h = email_hash(settings.secret_key, email)
                    if w.get(TrialClaim, h) is None:
                        w.add(TrialClaim(email_hash=h, claimed_at=now))
                w.commit()
        except IntegrityError:
            w.rollback()
    db.expire_all()
    return get_sub(db, bot_id)


def grandfather_all(db: Session, settings, now=None) -> int:
    """Sweep: grandfather every live bot that has no subscription row yet."""
    from sqlalchemy import exists

    missing = db.scalars(
        select(Bot.id).where(
            Bot.deleted_at.is_(None),
            Bot.status == "active",
            ~exists().where(Subscription.bot_id == Bot.id),
        )
    ).all()
    return sum(grandfather(db, settings, bot_id, now) is not None for bot_id in missing)


# --- plans ---------------------------------------------------------------------------


def plans(db: Session, active_only: bool = False) -> list[Plan]:
    q = select(Plan).order_by(Plan.is_trial.desc(), Plan.code)
    if active_only:
        q = q.where(Plan.active.is_(True))
    return list(db.scalars(q))


def plan_view(p: Plan) -> dict:
    return {
        "code": p.code,
        "name": p.name,
        "active": p.active,
        "is_trial": p.is_trial,
        "prices": json.loads(p.prices or "{}"),
        "limits": json.loads(p.limits or "{}"),
    }


def plan_limits(db: Session, settings, bot_id: str) -> dict[str, int]:
    """The bot's plan limits (empty with billing off or no plan row)."""
    if not enabled(settings):
        return {}
    sub = get_sub(db, bot_id)
    code = "trial" if sub is None or sub.status in ("none", "trialing") else sub.plan_code
    plan = db.get(Plan, code or "monthly")
    if plan is None:
        return {}
    raw = json.loads(plan.limits or "{}")
    return {k: int(v) for k, v in raw.items() if k in LIMIT_KEYS and isinstance(v, int)}


def price_for(plan: Plan, currency: str) -> dict | None:
    return json.loads(plan.prices or "{}").get(currency.upper())


# --- trial ---------------------------------------------------------------------------


def normalise_email(email: str) -> str:
    local, _, domain = email.strip().lower().partition("@")
    local = local.split("+", 1)[0]
    if domain in ("gmail.com", "googlemail.com"):
        local, domain = local.replace(".", ""), "gmail.com"
    return f"{local}@{domain}"


def email_hash(secret_key: str, email: str) -> str:
    return hmac.new(
        secret_key.encode(), normalise_email(email).encode(), hashlib.sha256
    ).hexdigest()


def start_trial(db: Session, settings, secret_key: str, bot_id: str, email: str, now=None):
    """At activation (sign-up without approval, or approval). One trial per e-mail, ever:
    a second account on the same address starts without one and must subscribe."""
    if not enabled(settings):
        return None
    now = now or utcnow()
    sub = ensure_sub(db, bot_id)
    if sub.status != "none" or sub.trial_started_at is not None:
        return sub
    h = email_hash(secret_key, email)
    if db.get(TrialClaim, h) is not None:
        logs.add(db, bot_id, None, "billing_trial_refused", detail="trial already used")
        return sub
    db.add(TrialClaim(email_hash=h, claimed_at=now))
    sub.trial_started_at = now
    sub.trial_ends_at = now + timedelta(days=settings.trial_days)
    sub.plan_code = "trial"
    new = state.transition(sub_state(sub), "trial_start", now)
    apply(db, sub, new, "trial", now)
    db.flush()
    return sub


def count_trial_message(db: Session, settings, bot_id: str) -> bool:
    """One trial message used. True when this one crossed 80% (send the warning once)."""
    if not enabled(settings):
        return False
    sub = get_sub(db, bot_id)
    if sub is None or sub.status != "trialing":
        return False
    # Atomic increment: concurrent chats must not lose counts.
    db.execute(
        update(Subscription)
        .where(Subscription.id == sub.id)
        .values(trial_messages_used=Subscription.trial_messages_used + 1)
        .execution_options(synchronize_session=False)
    )
    db.refresh(sub, ["trial_messages_used"])
    limit = max(1, settings.trial_messages)
    return sub.trial_messages_used >= 0.8 * limit and mark_notice(sub, "trial_msg80")


def mark_notice(sub: Subscription, key: str) -> bool:
    """Record that mail `key` went out; False if it already had."""
    sent = set(filter(None, (sub.notices or "").split(",")))
    if key in sent:
        return False
    sub.notices = ",".join(sorted(sent | {key}))
    return True


def owner_email(db: Session, bot_id: str) -> str | None:
    return db.scalar(select(Admin.email).where(Admin.bot_id == bot_id, Admin.deleted_at.is_(None)))


# --- webhooks ------------------------------------------------------------------------


def strip_pii(value):
    if isinstance(value, dict):
        return {k: strip_pii(v) for k, v in value.items() if k.lower() not in PII_KEYS}
    if isinstance(value, list):
        return [strip_pii(v) for v in value]
    return value


@dataclass
class Outcome:
    pings: list[str] = field(default_factory=list)
    note: str | None = None  # stored on the event (e.g. "unmatched"), not an error


def _find_sub(db: Session, ev: NormalizedEvent) -> Subscription | None:
    if ev.subscription_id:
        sub = db.scalar(
            select(Subscription).where(
                Subscription.provider == ev.provider,
                Subscription.provider_subscription_id == ev.subscription_id,
            )
        )
        if sub is not None:
            return sub
    if ev.bot_id:
        bot = db.get(Bot, ev.bot_id)
        if bot is not None and bot.deleted_at is None:
            return ensure_sub(db, bot.id)
    return None


def upsert_invoice(db: Session, bot_id: str, provider: str, inv: dict, now) -> None:
    row = db.scalar(
        select(Invoice).where(Invoice.provider_invoice_id == inv["provider_invoice_id"])
    )
    if row is None:
        row = Invoice(bot_id=bot_id, provider=provider, created_at=now, **inv)
        db.add(row)
    else:
        for k, v in inv.items():
            if v is not None:
                setattr(row, k, v)
    row.updated_at = now


def handle_event(db: Session, settings, ev: NormalizedEvent, now=None) -> Outcome:
    """Apply one verified event. Raises on bugs/DB errors (the caller records them)."""
    now = now or utcnow()
    out = Outcome()
    if ev.action is None:
        return out  # unknown / uninteresting type: stored only
    sub = _find_sub(db, ev)
    if sub is None:
        out.note = "unmatched"
        return out
    if ev.invoice:  # invoices are upserted whatever the order
        upsert_invoice(db, sub.bot_id, ev.provider, ev.invoice, now)
    current = sub.provider_subscription_id
    if ev.subscription_id and current and ev.subscription_id != current:
        if ev.action != "link" and sub.status in ("active", "past_due", "cancelled"):
            out.note = "other subscription"  # an old/replaced subscription: no status change
            return out
    if ev.subscription_id:
        sub.provider, sub.provider_subscription_id = ev.provider, ev.subscription_id
    sub.provider = sub.provider or ev.provider
    if ev.customer_id:
        sub.provider_customer_id = ev.customer_id
    if ev.plan_code and db.get(Plan, ev.plan_code) is not None:
        sub.plan_code = ev.plan_code
    if ev.currency:
        sub.currency = ev.currency
    if ev.action == "link":
        return out
    if sub.updated_from_event_at and ev.occurred_at and ev.occurred_at < sub.updated_from_event_at:
        out.note = "stale"
        return out
    action = ev.action
    if (
        action == "paid"
        and sub.status == "cancelled"
        and ev.type.startswith("customer.subscription.")
    ):
        action = "resume"  # Stripe: cancel_at_period_end switched off again (portal "renew")
    if sub.plan_code in (None, "trial") and action == "paid":
        sub.plan_code = "monthly"
    old = sub.status
    new = state.transition(
        sub_state(sub), action, now, grace_days=settings.billing_grace_days,
        period_end=ev.period_end,
    )  # fmt: skip
    apply(db, sub, new, f"{ev.provider}:{ev.type}", now)
    if ev.occurred_at:
        sub.updated_from_event_at = max(filter(None, (sub.updated_from_event_at, ev.occurred_at)))
    slug = db.scalar(select(Bot.slug).where(Bot.id == sub.bot_id)) or sub.bot_id
    if new.status == "active" and old in ("none", "trialing", "inactive"):
        out.pings.append(f"mebot: new subscription {slug} ({ev.provider})")
    elif new.status != old and (new.status == "cancelled" or action == "cancel_now"):
        out.pings.append(f"mebot: subscription cancelled {slug}")
    if action == "failed":
        out.pings.append(f"mebot: payment failed {slug}")
    return out


# --- sweep / reconciliation / comps ----------------------------------------------------


@dataclass
class SweepResult:
    expired: int = 0
    mails: list[tuple[str, str]] = field(default_factory=list)  # (to, template key)


def sweep(db: Session, settings, now=None) -> SweepResult:
    """Persist passed deadlines (grace, period end, trial) and queue owner notices."""
    from mebot.models import BillingEvent

    now = now or utcnow()
    res = SweepResult()
    if not enabled(settings):
        return res
    grandfather_all(db, settings, now)
    for sub in db.scalars(select(Subscription)).all():
        st = sub_state(sub)
        email = None
        if state.due_expiry(st, now, settings.trial_messages):
            was = sub.status
            apply(db, sub, state.transition(st, "expire", now), "deadline", now)
            res.expired += 1
            if was == "trialing" and mark_notice(sub, "trial_ended"):
                email = owner_email(db, sub.bot_id)
                if email:
                    res.mails.append((email, "trial_ended"))
        elif (
            sub.status == "trialing"
            and sub.trial_ends_at
            and sub.trial_ends_at - now <= TRIAL_WARN
            and mark_notice(sub, "trial_3days")
        ):
            email = owner_email(db, sub.bot_id)
            if email:
                res.mails.append((email, "trial_3days"))
        if (
            sub.status == "inactive"
            and sub.inactive_since
            and now - sub.inactive_since >= INACTIVE_REMINDER
            and mark_notice(sub, "inactive_90")
        ):
            email = owner_email(db, sub.bot_id)
            if email:
                res.mails.append((email, "inactive_90"))
    for ev in db.scalars(
        select(BillingEvent).where(
            BillingEvent.payload.is_not(None), BillingEvent.received_at < now - PAYLOAD_KEEP
        )
    ).all():
        ev.payload = None
    db.commit()
    return res


def reconcile_one(
    db: Session, sub: Subscription, remote: RemoteSub, provider, now=None, grace_days: int = 7
):
    """Make the local row match the provider. Returns "old->new" when it drifted."""
    now = now or utcnow()
    if remote.status is None:
        return None
    target = remote.status
    if target == "active" and sub.status == "cancelled" and not provider.reports_scheduled_cancel:
        target = "cancelled"  # Razorpay shows "active" until a scheduled cancel takes effect
    if remote.period_end:
        sub.current_period_end = remote.period_end
    if target == sub.status:
        return None
    old = sub.status
    new = replace(sub_state(sub), status=target)
    if target == "past_due":
        new = replace(new, grace_until=sub.grace_until or now + timedelta(days=grace_days))
    else:
        new = replace(new, grace_until=None)
    new = replace(new, cancel_at_period_end=(target == "cancelled"))
    apply(db, sub, new, "reconcile", now)
    return f"{old}->{target}"


def to_reconcile(db: Session) -> list[Subscription]:
    return list(
        db.scalars(
            select(Subscription).where(
                Subscription.status.in_(state.NON_TERMINAL),
                Subscription.provider_subscription_id.is_not(None),
            )
        )
    )


def comp(db: Session, bot_id: str, days: int, now=None) -> Subscription:
    """Operator grant: serving for N more days from now (or from an existing comp)."""
    now = now or utcnow()
    sub = ensure_sub(db, bot_id)
    base = sub.comp_until if sub.comp_until and sub.comp_until > now else now
    sub.comp_until = base + timedelta(days=days)
    sub.updated_at = now
    logs.add(db, bot_id, None, "billing_comp", detail=f"+{days}d")
    return sub
