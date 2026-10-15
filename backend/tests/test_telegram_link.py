import json
import re
from datetime import timedelta

import httpx
import respx
from sqlalchemy import select

from mebot.models import AccessLog, TelegramConfig, utcnow
from mebot.telegram.updates import LINK_FAILED, handle_update
from tests.conftest import csrf
from tests.tg_helpers import (
    BASE,
    OWNER_CHAT,
    TOKEN,
    ctx,
    link,
    mock_telegram,
    sent_texts,
    text_update,
)


def put_token(c, token=TOKEN):
    return c.put("/api/admin/telegram", json={"bot_token": token}, headers=csrf(c))


def config(app) -> TelegramConfig:
    with app.state.session_factory() as db:
        return db.scalar(select(TelegramConfig))


@respx.mock
def test_put_token_validates_and_stores_encrypted(admin_client, app):
    mock_telegram()
    r = put_token(admin_client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bot_username"] == "jane_mebot" and body["linked"] is False
    assert body["bot_token_last4"] == TOKEN[-4:] and body["configured"] is True
    assert TOKEN not in r.text
    row = config(app)
    assert row.bot_token_encrypted and TOKEN not in row.bot_token_encrypted
    view = admin_client.get("/api/admin/telegram").json()
    assert TOKEN not in json.dumps(view) and view["configured"] is True


@respx.mock
def test_invalid_token_422_nothing_stored(admin_client, app):
    respx.post(f"{BASE}/getMe").mock(
        return_value=httpx.Response(401, json={"ok": False, "error_code": 401})
    )
    r = put_token(admin_client)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "TELEGRAM_TOKEN_INVALID"
    assert TOKEN not in r.text
    assert config(app) is None


def test_malformed_token_rejected_without_call(admin_client):
    r = put_token(admin_client, "not a token")
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"] == "bot_token"


@respx.mock
def test_unreachable_telegram_is_friendly(admin_client):
    respx.post(f"{BASE}/getMe").mock(side_effect=httpx.ConnectError("x"))
    r = put_token(admin_client)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "TELEGRAM_UNREACHABLE"


def test_endpoints_need_auth_and_csrf(client, admin_client):
    assert admin_client.put("/api/admin/telegram", json={"bot_token": TOKEN}).status_code == 403
    admin_client.post("/api/auth/logout", headers=csrf(admin_client))
    assert admin_client.get("/api/admin/telegram").status_code == 401


def test_get_unconfigured(admin_client):
    body = admin_client.get("/api/admin/telegram").json()
    assert body["configured"] is False and body["linked"] is False


@respx.mock
async def test_deep_link_flow(admin_client, app):
    routes = mock_telegram()
    put_token(admin_client)
    r = admin_client.post("/api/admin/telegram/link", headers=csrf(admin_client))
    assert r.status_code == 200
    m = re.fullmatch(r"https://t\.me/jane_mebot\?start=([A-Za-z0-9_-]{16})", r.json()["deep_link"])
    assert m and r.json()["expires_at"].endswith("Z")
    code = m.group(1)
    row = config(app)
    assert row.link_code_hash and code not in row.link_code_hash
    bot_id = row.bot_id
    await handle_update(ctx(app), bot_id, text_update(f"/start {code}", chat_id="777"))
    assert admin_client.get("/api/admin/telegram").json()["linked"] is True
    assert config(app).chat_id == "777"
    assert sent_texts(routes)[-1].startswith("✅ Linked to")
    assert routes["setMyCommands"].called
    # the code is single-use
    await handle_update(ctx(app), bot_id, text_update(f"/start {code}", chat_id="888"))
    assert config(app).chat_id == "777"
    assert sent_texts(routes)[-1] == LINK_FAILED


@respx.mock
async def test_expired_and_wrong_codes(admin_client, app):
    routes = mock_telegram()
    put_token(admin_client)
    code = (
        admin_client.post("/api/admin/telegram/link", headers=csrf(admin_client))
        .json()["deep_link"]
        .split("start=")[1]
    )
    bot_id = config(app).bot_id
    await handle_update(ctx(app), bot_id, text_update("/start WRONGWRONGWRONG1", chat_id="9"))
    assert sent_texts(routes)[-1] == LINK_FAILED
    later = ctx(app, now=lambda: utcnow() + timedelta(minutes=11))
    await handle_update(later, bot_id, text_update(f"/start {code}", chat_id="9"))
    assert sent_texts(routes)[-1] == LINK_FAILED
    assert config(app).chat_id is None


@respx.mock
async def test_foreign_chat_ignored_and_logged_once(admin_client, app):
    routes = mock_telegram()
    bot_id = link(app)
    c = ctx(app)
    for _ in range(3):
        await handle_update(c, bot_id, text_update("/status", chat_id="666"))
    assert not routes["sendMessage"].called
    with app.state.session_factory() as db:
        rows = db.scalars(select(AccessLog).where(AccessLog.event == "TELEGRAM_FOREIGN_CHAT")).all()
    assert len(rows) == 1 and "666" in rows[0].detail and "/status" not in rows[0].detail


@respx.mock
def test_test_message_and_unlink(admin_client, app):
    routes = mock_telegram()
    link(app)
    r = admin_client.post("/api/admin/telegram/test", headers=csrf(admin_client))
    assert r.status_code == 204
    assert json.loads(routes["sendMessage"].calls.last.request.content)["chat_id"] == OWNER_CHAT
    r = admin_client.delete("/api/admin/telegram", headers=csrf(admin_client))
    assert r.status_code == 204
    row = config(app)
    assert row.bot_token_encrypted is None and row.chat_id is None
    assert admin_client.get("/api/admin/telegram").json()["configured"] is False


def test_test_requires_link(admin_client):
    r = admin_client.post("/api/admin/telegram/test", headers=csrf(admin_client))
    assert r.status_code == 409


@respx.mock
def test_test_send_failure_is_scrubbed(admin_client, app):
    link(app)
    respx.post(f"{BASE}/sendMessage").mock(
        return_value=httpx.Response(
            400, json={"ok": False, "error_code": 400, "description": f"chat not found {TOKEN}"}
        )
    )
    r = admin_client.post("/api/admin/telegram/test", headers=csrf(admin_client))
    assert r.status_code == 502 and TOKEN not in r.text
