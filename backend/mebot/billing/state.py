"""Subscription state machine. Pure: no DB, no clock; callers pass ``now``.

none -> trialing -> active -> past_due (grace) -> inactive, plus cancelled (serving until
the period ends, then inactive). A payment from past_due or inactive returns to active.
Events: trial_start, paid, failed, cancel_at_end, resume, cancel_now, expire (a deadline
passed: see due_expiry). Pairs missing from TABLE leave the status as it is.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

TABLE: dict[tuple[str, str], str] = {
    ("none", "trial_start"): "trialing",
    ("none", "paid"): "active",
    ("trialing", "paid"): "active",
    ("trialing", "cancel_now"): "inactive",
    ("trialing", "expire"): "inactive",
    ("active", "failed"): "past_due",
    ("active", "cancel_at_end"): "cancelled",
    ("active", "cancel_now"): "inactive",
    ("past_due", "paid"): "active",
    ("past_due", "cancel_at_end"): "cancelled",
    ("past_due", "cancel_now"): "inactive",
    ("past_due", "expire"): "inactive",
    ("cancelled", "resume"): "active",
    ("cancelled", "cancel_now"): "inactive",
    ("cancelled", "expire"): "inactive",
    ("inactive", "paid"): "active",
}
STATUSES = ("none", "trialing", "active", "past_due", "cancelled", "inactive")
# Statuses the reconciliation job asks the provider about.
NON_TERMINAL = ("active", "past_due", "cancelled")


@dataclass(frozen=True)
class SubState:
    status: str
    grace_until: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    trial_ends_at: datetime | None = None
    trial_messages_used: int = 0
    comp_until: datetime | None = None


def transition(
    s: SubState, event: str, now: datetime, *, grace_days: int = 7,
    period_end: datetime | None = None,
) -> SubState:  # fmt: skip
    to = TABLE.get((s.status, event), s.status)
    out = s
    if period_end is not None and event in ("paid", "cancel_at_end", "resume", "failed"):
        out = replace(out, current_period_end=period_end)
    if to == "past_due":
        out = replace(out, grace_until=s.grace_until or now + timedelta(days=grace_days))
    elif s.status == "past_due" or to != s.status:
        out = replace(out, grace_until=None)
    if to == "cancelled":
        out = replace(out, cancel_at_period_end=True)
    elif to in ("active", "inactive"):
        out = replace(out, cancel_at_period_end=False)
    return replace(out, status=to)


def due_expiry(s: SubState, now: datetime, trial_messages: int | None = None) -> bool:
    """Has a deadline passed that moves this subscription to inactive?"""
    if s.status == "past_due":
        return s.grace_until is not None and s.grace_until <= now
    if s.status == "cancelled":
        return s.current_period_end is None or s.current_period_end <= now
    if s.status == "trialing":
        if trial_messages is not None and s.trial_messages_used >= trial_messages:
            return True
        return s.trial_ends_at is None or s.trial_ends_at <= now
    return False


def serving(s: SubState, now: datetime, trial_messages: int | None = None) -> bool:
    """May the bot answer the public? Deadlines count even before the sweep persists them."""
    if s.comp_until is not None and s.comp_until > now:
        return True
    if s.status in ("trialing", "past_due", "cancelled"):
        return not due_expiry(s, now, trial_messages)
    return s.status == "active"
