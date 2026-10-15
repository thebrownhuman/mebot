import json

import pytest
import respx
from sqlalchemy import select

from mebot.models import Contact, TelegramConfig
from mebot.telegram import outbox
from tests.conftest import csrf
from tests.tg_helpers import TOKEN, link, mock_telegram


def patch(c, body):
    return c.patch("/api/admin/telegram", json=body, headers=csrf(c))


def cfg(app) -> TelegramConfig:
    with app.state.session_factory() as db:
        return db.scalar(select(TelegramConfig))


def test_patch_toggles_digest_and_timezone(admin_client, app):
    link(app)
    r = patch(
        admin_client,
        {"notify_every_question": True, "digest_hour": 8, "timezone": "Asia/Kolkata"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["notify_every_question"] is True and body["digest_hour"] == 8
    assert body["timezone"] == "Asia/Kolkata" and body["notify_unanswered"] is True
    assert TOKEN not in r.text


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"digest_hour": 24}, "digest_hour"),
        ({"digest_hour": -1}, "digest_hour"),
        ({"timezone": "Mars/Olympus"}, "timezone"),
        ({"mode": "carrier-pigeon"}, "mode"),
        ({"notify_contact": None}, "notify_contact"),
    ],
)
def test_patch_validation(admin_client, app, body, field):
    link(app)
    r = patch(admin_client, body)
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"] == field


def test_patch_requires_configured(admin_client):
    assert patch(admin_client, {"digest_hour": 9}).status_code == 409


@respx.mock
def test_webhook_mode_needs_public_url_then_sets_webhook(admin_client, app):
    routes = mock_telegram()
    bot_id = link(app)
    r = patch(admin_client, {"mode": "webhook"})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "mode"
    app.state.settings.public_url = "https://bot.example.com"
    r = patch(admin_client, {"mode": "webhook"})
    assert r.status_code == 200 and r.json()["mode"] == "webhook"
    sent = json.loads(routes["setWebhook"].calls.last.request.content)
    assert sent["url"] == f"https://bot.example.com/api/telegram/webhook/{bot_id}"
    row = cfg(app)
    assert row.webhook_secret and sent["secret_token"] == row.webhook_secret
    assert row.webhook_secret not in r.text
    r = patch(admin_client, {"mode": "polling"})
    assert r.json()["mode"] == "polling" and routes["deleteWebhook"].called
    assert cfg(app).webhook_secret is None


def test_outbox_health(admin_client, app):
    bot_id = link(app)
    with app.state.session_factory() as db:
        a = outbox.enqueue(db, bot_id, "k", {"text": "a"})
        b = outbox.enqueue(db, bot_id, "k", {"text": "b"})
        outbox.enqueue(db, bot_id, "k", {"text": "c"})
        a.status = "sent"
        b.status = "dead"
        db.commit()
    body = admin_client.get("/api/admin/telegram").json()["outbox"]
    assert body["pending"] == 1 and body["dead"] == 1 and body["failed"] == 0
    assert body["last_sent_at"].endswith("Z")


# --- contacts ------------------------------------------------------------------------


def test_contacts_list_and_soft_delete(admin_client, app):
    admin_client.post("/api/contact", json={"name": "A", "email": "a@x.io"})
    admin_client.post("/api/contact", json={"name": "B", "email": "b@x.io", "company": "Co"})
    items = admin_client.get("/api/admin/contacts").json()["items"]
    assert [i["name"] for i in items] == ["B", "A"]  # newest first
    assert set(items[0]) >= {
        "id",
        "name",
        "email",
        "company",
        "role",
        "note",
        "session_id",
        "created_at",
    }
    r = admin_client.delete(f"/api/admin/contacts/{items[0]['id']}", headers=csrf(admin_client))
    assert r.status_code == 204
    assert [i["name"] for i in admin_client.get("/api/admin/contacts").json()["items"]] == ["A"]
    with app.state.session_factory() as db:
        assert db.scalar(select(Contact).where(Contact.name == "B")).deleted_at is not None
    assert (
        admin_client.delete(
            f"/api/admin/contacts/{items[0]['id']}", headers=csrf(admin_client)
        ).status_code
        == 404
    )


def test_contacts_need_auth(admin_client):
    admin_client.post("/api/auth/logout", headers=csrf(admin_client))
    assert admin_client.get("/api/admin/contacts").status_code == 401
