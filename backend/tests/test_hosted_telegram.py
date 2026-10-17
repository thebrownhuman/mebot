"""Hosted mode: Telegram is webhook-only, per tenant."""

import json

import respx
from sqlalchemy import select

from mebot.models import TelegramConfig
from mebot.telegram.service import TelegramService
from tests.conftest import csrf
from tests.tg_helpers import TOKEN, mock_telegram


@respx.mock
def test_saving_token_switches_to_webhook_with_per_bot_path(tenants, hosted_app):
    routes = mock_telegram()
    a, _ = tenants
    r = a.client.put("/api/admin/telegram", json={"bot_token": TOKEN}, headers=csrf(a.client))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "webhook" and body["webhook_only"] is True
    sent = json.loads(routes["setWebhook"].calls.last.request.content)
    assert sent["url"] == f"https://mebot.example/api/telegram/webhook/{a.bot_id}"
    with hosted_app.state.session_factory() as db:
        row = db.scalar(select(TelegramConfig).where(TelegramConfig.bot_id == a.bot_id))
        assert row.webhook_secret == sent["secret_token"]


@respx.mock
def test_polling_refused_in_hosted(tenants):
    mock_telegram()
    a, _ = tenants
    a.client.put("/api/admin/telegram", json={"bot_token": TOKEN}, headers=csrf(a.client))
    r = a.client.patch("/api/admin/telegram", json={"mode": "polling"}, headers=csrf(a.client))
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "mode"


def test_supervisor_never_polls_in_hosted(hosted_app):
    with hosted_app.state.session_factory() as db:
        db.add(TelegramConfig(bot_id="x", mode="polling", enabled=True, bot_token_encrypted="e"))
        db.commit()
    svc: TelegramService = hosted_app.state.telegram
    assert svc._wanted() == set()
