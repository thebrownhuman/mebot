"""Operator billing view: MRR, past-due, reconcile, comps, plan edits, CLI. No content."""

import json
from datetime import timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from mebot import cli
from mebot.auth import passwords
from mebot.billing import service
from mebot.hosted import operator as op
from mebot.models import Message, Plan, PlatformAudit, Skill, utcnow
from tests.billing_helpers import sub_row
from tests.conftest import LLM_KEY, csrf, make_tenant

OP_EMAIL, OP_PASSWORD = "ops@example.com", "operator password 1"
MARK = "ZQXCONTENTSECRET"
CONTENT_WORDS = ("conversation", "message", "profile", "prompt", "llm", "key", "contact")


def _operator(app):
    with app.state.session_factory() as db:
        op.create_admin(db, OP_EMAIL, passwords.hash_password(OP_PASSWORD))
        db.commit()
    c = TestClient(app)
    c.__enter__()
    r = c.post(
        "/api/platform/auth/login",
        json={"email": OP_EMAIL, "password": OP_PASSWORD},
        headers=csrf(c),
    )
    assert r.status_code == 204, r.text
    return c


@pytest.fixture
def ops(billing_app):
    with billing_app.state.session_factory() as db:
        db.get(Plan, "monthly").prices = json.dumps(
            {
                "INR": {"amount_minor": 49900, "provider": "razorpay", "provider_plan_id": "p"},
                "USD": {"amount_minor": 900, "provider": "stripe", "provider_plan_id": "price"},
            }
        )
        db.commit()
    c = _operator(billing_app)
    yield c
    c.__exit__(None, None, None)


def _sub(app, bot_id, **fields):
    with app.state.session_factory() as db:
        sub = service.ensure_sub(db, bot_id)
        for k, v in fields.items():
            setattr(sub, k, v)
        db.commit()


def _audit(app):
    with app.state.session_factory() as db:
        return [
            (a.action, a.detail) for a in db.query(PlatformAudit).order_by(PlatformAudit.created_at)
        ]


def test_overview_mrr_counts_past_due_and_tenant_columns(ops, billing_app):
    a, b, c, d = (make_tenant(billing_app, s) for s in ("alice", "bobby", "carol", "dave1"))
    _sub(billing_app, a.bot_id, status="active", plan_code="monthly", currency="INR")
    _sub(billing_app, b.bot_id, status="past_due", plan_code="monthly", currency="USD",
         grace_until=utcnow() + timedelta(days=2), provider="stripe")  # fmt: skip
    _sub(billing_app, c.bot_id, status="inactive", plan_code="monthly", currency="USD")
    _sub(billing_app, d.bot_id, status="trialing", trial_ends_at=utcnow() + timedelta(days=3))
    v = ops.get("/api/platform/billing").json()
    assert v["enabled"] and v["mrr"] == {"INR": 49900, "USD": 900}
    assert v["counts"] == {"active": 1, "past_due": 1, "inactive": 1, "trialing": 1}
    assert [p["slug"] for p in v["past_due"]] == ["bobby"]
    assert {p["code"] for p in v["plans"]} == {"trial", "monthly"}
    rows = {t["slug"]: t for t in ops.get("/api/platform/tenants").json()["items"]}
    assert (
        rows["alice"]["billing_status"] == "active" and rows["alice"]["billing_plan"] == "monthly"
    )
    for t in (a, b, c, d):
        t.client.__exit__(None, None, None)


def test_comp_grants_days_and_audits(ops, billing_app):
    t = make_tenant(billing_app, "alice")
    with TestClient(billing_app) as anon:
        assert anon.get("/b/alice/api/public/config").status_code == 404
        r = ops.post(f"/api/platform/tenants/{t.bot_id}/comp", json={"days": 10, "reason": "beta"},
                     headers=csrf(ops))  # fmt: skip
        assert r.status_code == 200
        assert anon.get("/b/alice/api/public/config").status_code == 200
    assert ("billing_comp", "+10d: beta") in _audit(billing_app)
    bad = ops.post(f"/api/platform/tenants/{t.bot_id}/comp", json={"days": 0, "reason": "x"},
                   headers=csrf(ops))  # fmt: skip
    assert bad.status_code == 422
    t.client.__exit__(None, None, None)


@respx.mock
def test_reconcile_now_button(ops, billing_app):
    t = make_tenant(billing_app, "alice")
    _sub(
        billing_app, t.bot_id, status="active", provider="stripe", provider_subscription_id="sub_1"
    )
    respx.get("https://api.stripe.com/v1/subscriptions/sub_1").mock(
        return_value=httpx.Response(200, json={"id": "sub_1", "status": "canceled"})
    )
    r = ops.post("/api/platform/billing/reconcile", headers=csrf(ops))
    assert r.json() == {"checked": 1, "fixed": 1, "errors": 0}
    assert sub_row(billing_app, t.bot_id).status == "inactive"
    actions = [a for a, _ in _audit(billing_app)]
    assert "billing_drift_fixed" in actions and "billing_reconcile" in actions
    t.client.__exit__(None, None, None)


def test_plan_edit_validates_and_audits(ops, billing_app):
    usd = {"amount_minor": 1200, "provider": "stripe", "provider_plan_id": "price_2"}
    body = {"prices": {"USD": usd}, "limits": {"daily_message_cap": 300, "imports_per_day": 5}}
    r = ops.put("/api/platform/plans/monthly", json=body, headers=csrf(ops))
    assert r.status_code == 200 and r.json()["limits"]["imports_per_day"] == 5
    for bad in (
        {"prices": {"INR": {"amount_minor": 1, "provider": "stripe", "provider_plan_id": "x"}}},
        {"prices": {"usd": {"amount_minor": 1, "provider": "stripe", "provider_plan_id": "x"}}},
        {"limits": {"bogus": 1}},
        {"limits": {"daily_message_cap": 0}},
    ):
        assert (
            ops.put("/api/platform/plans/monthly", json=bad, headers=csrf(ops)).status_code == 422
        )
    assert ops.put("/api/platform/plans/nope", json={}, headers=csrf(ops)).status_code == 404
    assert ("plan_updated", "monthly: limits, prices") in _audit(billing_app)


def test_operator_billing_routes_expose_no_content(ops, billing_app):
    t = make_tenant(billing_app, "alice")
    with billing_app.state.session_factory() as db:
        db.add(Skill(bot_id=t.bot_id, name=MARK))
        db.add(Message(bot_id=t.bot_id, session_id="s1", role="user", content=MARK))
        db.commit()
    paths = [p for p in billing_app.openapi()["paths"] if p.startswith("/api/platform")]
    for p in paths:
        assert not any(w in p for w in CONTENT_WORDS), p
    for p in ("/api/platform/billing", "/api/platform/tenants"):
        r = ops.get(p)
        assert MARK not in r.text and LLM_KEY not in r.text and "sk_test" not in r.text
    assert ops.get("/api/hosted/billing").status_code == 401  # operator isn't an owner
    t.client.__exit__(None, None, None)


def test_billing_actions_need_operator_and_billing(tenants, hosted_app):
    a, _ = tenants
    assert a.client.get("/api/platform/billing").status_code == 401
    c = _operator(hosted_app)
    assert c.get("/api/platform/billing").json()["enabled"] is False
    r = c.post(f"/api/platform/tenants/{a.bot_id}/comp", json={"days": 3, "reason": "x"},
               headers=csrf(c))  # fmt: skip
    assert r.status_code == 404
    c.__exit__(None, None, None)


def test_cli_plans(hosted_settings, monkeypatch, capsys):
    from mebot.db import make_session_factory

    monkeypatch.setattr(cli, "Settings", lambda: hosted_settings)
    assert cli.main(["plans", "set-price", "monthly", "inr", "49900", "razorpay", "plan_X"]) == 0
    assert cli.main(["plans", "set-price", "monthly", "USD", "900", "razorpay", "plan_X"]) == 1
    assert cli.main(["plans", "set-limit", "monthly", "daily_message_cap", "250"]) == 0
    assert cli.main(["plans", "set-limit", "monthly", "bogus", "1"]) == 1
    assert cli.main(["plans", "list"]) == 0
    with make_session_factory(hosted_settings.database_url)() as db:
        view = service.plan_view(db.get(Plan, "monthly"))
    assert view["prices"]["INR"]["provider_plan_id"] == "plan_X"
    assert view["limits"] == {"daily_message_cap": 250}
