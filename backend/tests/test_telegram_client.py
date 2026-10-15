import json
import logging

import httpx
import pytest
import respx

from mebot.crypto import decrypt_secret, encrypt_secret
from mebot.telegram.client import TelegramClient, TelegramError

TOKEN = "123456:AAH-secret-TOKEN-zz99"
BASE = f"https://api.telegram.org/bot{TOKEN}"


def ok(result) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


def body(route) -> dict:
    return json.loads(route.calls.last.request.content)


@respx.mock
async def test_get_me():
    respx.post(f"{BASE}/getMe").mock(return_value=ok({"id": 1, "username": "jane_mebot"}))
    me = await TelegramClient(TOKEN).get_me()
    assert me["username"] == "jane_mebot"


@respx.mock
async def test_send_message_shape():
    route = respx.post(f"{BASE}/sendMessage").mock(return_value=ok({"message_id": 77}))
    kb = {"inline_keyboard": [[{"text": "Reply", "callback_data": "reply:n1"}]]}
    mid = await TelegramClient(TOKEN).send_message("42", "<b>hi</b>", reply_markup=kb)
    assert mid == 77
    assert body(route) == {
        "chat_id": "42",
        "text": "<b>hi</b>",
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": kb,
    }


@respx.mock
async def test_force_reply_and_reply_to():
    route = respx.post(f"{BASE}/sendMessage").mock(return_value=ok({"message_id": 5}))
    await TelegramClient(TOKEN).send_message(
        "42", "Your answer to: x", force_reply=True, reply_to=9
    )
    b = body(route)
    assert b["reply_markup"] == {"force_reply": True}
    assert b["reply_parameters"] == {"message_id": 9, "allow_sending_without_reply": True}


@respx.mock
async def test_other_methods():
    c = TelegramClient(TOKEN)
    r1 = respx.post(f"{BASE}/answerCallbackQuery").mock(return_value=ok(True))
    await c.answer_callback_query("cb1", "Saved")
    assert body(r1) == {"callback_query_id": "cb1", "text": "Saved"}
    r2 = respx.post(f"{BASE}/editMessageReplyMarkup").mock(return_value=ok(True))
    await c.edit_reply_markup("42", 7, {"inline_keyboard": []})
    assert body(r2) == {"chat_id": "42", "message_id": 7, "reply_markup": {"inline_keyboard": []}}
    r3 = respx.post(f"{BASE}/getUpdates").mock(return_value=ok([{"update_id": 3}]))
    assert await c.get_updates(offset=3) == [{"update_id": 3}]
    assert body(r3) == {
        "offset": 3,
        "timeout": 25,
        "allowed_updates": ["message", "callback_query"],
    }
    r4 = respx.post(f"{BASE}/setWebhook").mock(return_value=ok(True))
    await c.set_webhook("https://x.example/api/telegram/webhook/b1", "sec")
    assert body(r4)["secret_token"] == "sec" and body(r4)["url"].endswith("/b1")
    r5 = respx.post(f"{BASE}/deleteWebhook").mock(return_value=ok(True))
    await c.delete_webhook()
    assert r5.called
    r6 = respx.post(f"{BASE}/setMyCommands").mock(return_value=ok(True))
    await c.set_my_commands([("status", "Status")])
    assert body(r6) == {"commands": [{"command": "status", "description": "Status"}]}


@respx.mock
@pytest.mark.parametrize(
    ("status", "payload", "kind"),
    [
        (401, {"ok": False, "error_code": 401, "description": "Unauthorized"}, "auth"),
        (404, {"ok": False, "error_code": 404, "description": "Not Found"}, "auth"),
        (400, {"ok": False, "error_code": 400, "description": f"bad {TOKEN}"}, "bad_request"),
        (502, {"ok": False, "error_code": 502, "description": "Bad Gateway"}, "server"),
    ],
)
async def test_errors_are_typed_and_scrubbed(status, payload, kind, caplog):
    respx.post(f"{BASE}/sendMessage").mock(return_value=httpx.Response(status, json=payload))
    caplog.set_level(logging.DEBUG)
    with pytest.raises(TelegramError) as ei:
        await TelegramClient(TOKEN).send_message("1", "x")
    assert ei.value.kind == kind and ei.value.status == status
    assert TOKEN not in str(ei.value) and TOKEN not in repr(ei.value.args)
    assert TOKEN not in caplog.text


@respx.mock
async def test_429_carries_retry_after():
    respx.post(f"{BASE}/sendMessage").mock(
        return_value=httpx.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests: retry after 7",
                "parameters": {"retry_after": 7},
            },
        )
    )
    with pytest.raises(TelegramError) as ei:
        await TelegramClient(TOKEN).send_message("1", "x")
    assert ei.value.kind == "rate_limit" and ei.value.retry_after == 7


@respx.mock
@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (httpx.ConnectError(f"cannot connect {BASE}"), "unreachable"),
        (httpx.ReadTimeout(BASE), "timeout"),
    ],
)
async def test_network_errors_never_contain_token(exc, kind):
    respx.post(f"{BASE}/getMe").mock(side_effect=exc)
    with pytest.raises(TelegramError) as ei:
        await TelegramClient(TOKEN).get_me()
    assert ei.value.kind == kind
    assert TOKEN not in str(ei.value)
    # `from None`: the httpx exception (whose text holds the URL) isn't chained in.
    assert ei.value.__cause__ is None and ei.value.__suppress_context__


def test_client_repr_hides_token():
    assert TOKEN not in repr(TelegramClient(TOKEN))


def test_token_encryption_uses_separate_key():
    enc = encrypt_secret("sk", TOKEN, info=b"mebot-telegram")
    assert decrypt_secret("sk", enc, info=b"mebot-telegram") == TOKEN
    assert decrypt_secret("sk", enc) is None  # LLM key derivation can't read it
