import respx

from mebot.telegram.updates import handle_update
from tests.test_chat_limits import chat
from tests.tg_helpers import ctx, link, mock_telegram, sent_texts, text_update


async def say(app, bot_id, text, chat_id=None):
    upd = text_update(text) if chat_id is None else text_update(text, chat_id=chat_id)
    await handle_update(ctx(app), bot_id, upd)


@respx.mock
async def test_help(admin_client, app):
    routes = mock_telegram()
    bot_id = link(app)
    await say(app, bot_id, "/help")
    t = sent_texts(routes)[-1]
    for c in ("/status", "/pause", "/resume", "/today", "/questions", "/help"):
        assert c in t


@respx.mock
async def test_pause_resume_from_telegram(admin_client, app):
    routes = mock_telegram()
    bot_id = link(app)
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    await say(app, bot_id, "/pause")
    assert sent_texts(routes)[-1].startswith("⏸️ Paused")
    assert chat(admin_client, sid).json()["error"]["code"] == "BOT_PAUSED"
    await say(app, bot_id, "/pause@jane_mebot")
    assert sent_texts(routes)[-1] == "Already paused."
    await say(app, bot_id, "/resume")
    assert sent_texts(routes)[-1].startswith("▶️ Resumed")
    assert chat(admin_client, sid).status_code == 200


@respx.mock
async def test_status_and_today(admin_client, app):
    routes = mock_telegram()
    bot_id = link(app)
    sid = admin_client.post("/api/session", json={"recruiter_name": "Bo"}).json()["session_id"]
    chat(admin_client, sid, "Which stack?")
    await say(app, bot_id, "/status")
    t = sent_texts(routes)[-1]
    assert "🟢 running" in t and "Messages today (UTC): 1/500" in t
    assert "Chats: 1 · Messages: 1" in t
    await say(app, bot_id, "/today")
    assert "Today so far" in sent_texts(routes)[-1]
    assert "which stack? (1)" in sent_texts(routes)[-1]


@respx.mock
async def test_commands_only_from_linked_chat(admin_client, app):
    routes = mock_telegram()
    bot_id = link(app)
    await say(app, bot_id, "/pause", chat_id="999")
    await say(app, bot_id, "/status", chat_id="999")
    assert not routes["sendMessage"].called
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    assert chat(admin_client, sid).status_code == 200


@respx.mock
async def test_unknown_command(admin_client, app):
    routes = mock_telegram()
    bot_id = link(app)
    await say(app, bot_id, "/frobnicate")
    assert sent_texts(routes)[-1].startswith("Unknown command.")
