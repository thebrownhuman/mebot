"""Shared helpers for Telegram tests (no network: everything goes through respx)."""

import json

import httpx
import respx

from mebot.repos import bots
from mebot.telegram import repo
from mebot.telegram.updates import TgContext

TOKEN = "987654:AAF-owner-BOT-token-q1w2"
BASE = f"https://api.telegram.org/bot{TOKEN}"
OWNER_CHAT = "5550001"


def ok(result) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


def mock_telegram(start_id: int = 100) -> dict:
    """Mock every Bot API method; sendMessage returns increasing message ids.
    Call inside an active respx mock. Returns the routes by method name."""
    counter = {"n": start_id}

    def send(request):
        counter["n"] += 1
        return ok({"message_id": counter["n"]})

    routes = {
        "getMe": respx.post(f"{BASE}/getMe").mock(
            return_value=ok({"id": 1, "is_bot": True, "username": "jane_mebot"})
        ),
        "sendMessage": respx.post(f"{BASE}/sendMessage").mock(side_effect=send),
    }
    for m in (
        "answerCallbackQuery",
        "editMessageReplyMarkup",
        "setMyCommands",
        "setWebhook",
        "deleteWebhook",
    ):
        routes[m] = respx.post(f"{BASE}/{m}").mock(return_value=ok(True))
    routes["getUpdates"] = respx.post(f"{BASE}/getUpdates").mock(return_value=ok([]))
    return routes


def sent_texts(routes) -> list[str]:
    return [json.loads(c.request.content)["text"] for c in routes["sendMessage"].calls]


def sent(routes) -> list[dict]:
    return [json.loads(c.request.content) for c in routes["sendMessage"].calls]


def link(app, chat_id: str = OWNER_CHAT, **over):
    """Store the token and link the owner's chat directly (bypasses /start)."""
    with app.state.session_factory() as db:
        bot = bots.get_primary(db)
        row = repo.save_token(db, bot.id, app.state.secret_key, TOKEN, "jane_mebot")
        row.chat_id = chat_id
        for k, v in over.items():
            setattr(row, k, v)
        db.commit()
        return bot.id


def ctx(app, now=None) -> TgContext:
    c = TgContext(app.state.session_factory, app.state.secret_key, app.state.settings)
    if now is not None:
        c.now = now
    return c


_uid = {"n": 1000}


def text_update(text: str, chat_id: str = OWNER_CHAT, reply_to: int | None = None) -> dict:
    _uid["n"] += 1
    msg = {"message_id": _uid["n"], "chat": {"id": int(chat_id)}, "text": text}
    if reply_to is not None:
        msg["reply_to_message"] = {"message_id": reply_to}
    return {"update_id": _uid["n"], "message": msg}


def callback_update(data: str, message_id: int = 1, chat_id: str = OWNER_CHAT) -> dict:
    _uid["n"] += 1
    return {
        "update_id": _uid["n"],
        "callback_query": {
            "id": f"cb{_uid['n']}",
            "data": data,
            "message": {"message_id": message_id, "chat": {"id": int(chat_id)}},
        },
    }
