"""The subscription state machine: one pure function, table-driven."""

from datetime import UTC, datetime, timedelta

import pytest

from mebot.billing.state import SubState, due_expiry, serving, transition

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)
LATER = NOW + timedelta(days=30)

# (from, event) -> to. Pairs not listed must leave the status unchanged.
TABLE = {
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
EVENTS = ("trial_start", "paid", "failed", "cancel_at_end", "resume", "cancel_now", "expire")


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("event", EVENTS)
def test_transition_table(status, event):
    out = transition(SubState(status), event, NOW, grace_days=7)
    assert out.status == TABLE.get((status, event), status)


def test_unknown_event_is_a_no_op():
    s = SubState("active", current_period_end=LATER)
    assert transition(s, "something_new", NOW) == s


def test_failed_payment_starts_grace_once():
    s = transition(SubState("active"), "failed", NOW, grace_days=7)
    assert s.grace_until == NOW + timedelta(days=7)
    again = transition(s, "failed", NOW + timedelta(days=3), grace_days=7)
    assert again.grace_until == NOW + timedelta(days=7)  # retries don't extend grace
    paid = transition(again, "paid", NOW + timedelta(days=4), period_end=LATER)
    assert paid.status == "active" and paid.grace_until is None
    assert paid.current_period_end == LATER


def test_cancel_at_end_keeps_period_and_resume_clears_it():
    s = transition(SubState("active", current_period_end=LATER), "cancel_at_end", NOW)
    assert s.status == "cancelled" and s.cancel_at_period_end and s.current_period_end == LATER
    r = transition(s, "resume", NOW)
    assert r.status == "active" and not r.cancel_at_period_end


def test_due_expiry():
    grace = SubState("past_due", grace_until=NOW)
    assert due_expiry(grace, NOW) and not due_expiry(grace, NOW - timedelta(seconds=1))
    cancelled = SubState("cancelled", current_period_end=NOW, cancel_at_period_end=True)
    assert due_expiry(cancelled, NOW)
    assert not due_expiry(SubState("cancelled", current_period_end=LATER), NOW)
    trial = SubState("trialing", trial_ends_at=LATER, trial_messages_used=10)
    assert not due_expiry(trial, NOW, trial_messages=200)
    assert due_expiry(trial, NOW, trial_messages=10)  # allowance used up first
    assert due_expiry(SubState("trialing", trial_ends_at=NOW), NOW, trial_messages=200)
    assert not due_expiry(SubState("active", current_period_end=NOW - timedelta(days=9)), NOW)


@pytest.mark.parametrize(
    "state,expected",
    [
        (SubState("none"), False),
        (SubState("trialing", trial_ends_at=LATER), True),
        (SubState("trialing", trial_ends_at=NOW - timedelta(seconds=1)), False),
        (SubState("active"), True),
        (SubState("past_due", grace_until=LATER), True),
        (SubState("past_due", grace_until=NOW), False),
        (SubState("cancelled", current_period_end=LATER), True),
        (SubState("cancelled", current_period_end=NOW), False),
        (SubState("inactive"), False),
        (SubState("inactive", comp_until=LATER), True),
        (SubState("none", comp_until=NOW), False),
    ],
)
def test_serving(state, expected):
    assert serving(state, NOW, trial_messages=200) is expected
