import json

import respx
from sqlalchemy import select

from mebot.models import AccessLog, Faq, Message, Notification
from mebot.telegram import outbox
from mebot.telegram.replies import NO_MATCH
from mebot.telegram.updates import handle_update
from tests.test_chat_limits import chat
from tests.tg_helpers import callback_update, ctx, link, mock_telegram, sent, text_update


async def unanswered_sent(admin_client, app, fake_llm, question="Expected CTC?"):
    """A visitor's unanswered question, delivered to Telegram. Returns (bot, sid, note)."""
    bot_id = link(app)
    fake_llm.chunks = ["Not sure. [[UNANSWERED]]"]
    sid = admin_client.post("/api/session", json={"recruiter_name": "Priya"}).json()["session_id"]
    chat(admin_client, sid, question)
    c = ctx(app)

    async def no_sleep(_):
        return None

    c.sleep = no_sleep
    await outbox.send_due(c)
    with app.state.session_factory() as db:
        n = db.scalar(select(Notification).where(Notification.kind == "unanswered"))
    assert n.telegram_message_id
    return bot_id, sid, n


def owner_messages(app, sid):
    with app.state.session_factory() as db:
        return list(
            db.scalars(
                select(Message).where(Message.session_id == sid, Message.from_owner.is_(True))
            )
        )


@respx.mock
async def test_direct_reply_reaches_session(admin_client, app, fake_llm):
    routes = mock_telegram()
    bot_id, sid, n = await unanswered_sent(admin_client, app, fake_llm)
    upd = text_update("Around 30 LPA, negotiable.", reply_to=n.telegram_message_id)
    await handle_update(ctx(app), bot_id, upd)
    [m] = owner_messages(app, sid)
    assert m.role == "assistant" and m.content == "Around 30 LPA, negotiable."
    last = sent(routes)[-1]
    assert last["text"] == "✅ Sent to <b>Priya</b>."
    assert last["reply_markup"]["inline_keyboard"][0][0]["text"] == "Save to FAQ"
    with app.state.session_factory() as db:
        assert db.scalar(select(AccessLog).where(AccessLog.event == "OWNER_REPLIED"))


@respx.mock
async def test_reply_button_force_reply_then_answer(admin_client, app, fake_llm):
    routes = mock_telegram()
    bot_id, sid, n = await unanswered_sent(admin_client, app, fake_llm, "Notice <period>?")
    await handle_update(ctx(app), bot_id, callback_update(f"reply:{n.id}"))
    prompt = sent(routes)[-1]
    assert prompt["reply_markup"] == {"force_reply": True}
    assert prompt["text"] == "Your answer to: <i>Notice &lt;period&gt;?</i>"
    assert routes["answerCallbackQuery"].called
    prompt_id = int(routes["sendMessage"].calls.last.response.json()["result"]["message_id"])
    await handle_update(ctx(app), bot_id, text_update("30 days", reply_to=prompt_id))
    assert [m.content for m in owner_messages(app, sid)] == ["30 days"]


@respx.mock
async def test_save_to_faq_once(admin_client, app, fake_llm):
    routes = mock_telegram()
    bot_id, sid, n = await unanswered_sent(admin_client, app, fake_llm, "Expected CTC?")
    await handle_update(ctx(app), bot_id, text_update("30 LPA", reply_to=n.telegram_message_id))
    faq_cb = sent(routes)[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    for _ in range(3):
        await handle_update(ctx(app), bot_id, callback_update(faq_cb, message_id=555))
    with app.state.session_factory() as db:
        faqs = db.scalars(select(Faq).where(Faq.deleted_at.is_(None))).all()
    assert [(f.question, f.answer) for f in faqs] == [("Expected CTC?", "30 LPA")]
    edit = json.loads(routes["editMessageReplyMarkup"].calls.last.request.content)
    assert edit["message_id"] == 555
    assert edit["reply_markup"]["inline_keyboard"][0][0]["text"] == "Saved ✓"


@respx.mock
async def test_reply_to_unrelated_message_cannot_match(admin_client, app, fake_llm):
    routes = mock_telegram()
    bot_id, sid, n = await unanswered_sent(admin_client, app, fake_llm)
    await handle_update(ctx(app), bot_id, text_update("hello", reply_to=99999))
    assert sent(routes)[-1]["text"] == NO_MATCH
    assert owner_messages(app, sid) == []


@respx.mock
async def test_reply_to_non_unanswered_kind(admin_client, app, fake_llm):
    routes = mock_telegram()
    bot_id = link(app)
    admin_client.post("/api/session", json={"recruiter_name": "X"})
    c = ctx(app)

    async def no_sleep(_):
        return None

    c.sleep = no_sleep
    await outbox.send_due(c)  # the "new chat" ping
    with app.state.session_factory() as db:
        n = db.scalar(select(Notification).where(Notification.kind == "new_session"))
    await handle_update(ctx(app), bot_id, text_update("hi", reply_to=n.telegram_message_id))
    assert sent(routes)[-1]["text"] == NO_MATCH


@respx.mock
async def test_stranger_cannot_reply(admin_client, app, fake_llm):
    mock_telegram()
    bot_id, sid, n = await unanswered_sent(admin_client, app, fake_llm)
    upd = text_update("pwned", chat_id="31337", reply_to=n.telegram_message_id)
    await handle_update(ctx(app), bot_id, upd)
    assert owner_messages(app, sid) == []


# --- recruiter updates endpoint ----------------------------------------------------


@respx.mock
async def test_updates_endpoint_returns_only_new_owner_messages(admin_client, app, fake_llm):
    mock_telegram()
    bot_id, sid, n = await unanswered_sent(admin_client, app, fake_llm)
    r = admin_client.get(f"/api/session/{sid}/updates")
    assert r.json() == {"messages": [], "unanswered": True}
    await handle_update(ctx(app), bot_id, text_update("first", reply_to=n.telegram_message_id))
    msgs = admin_client.get(f"/api/session/{sid}/updates").json()["messages"]
    assert [m["content"] for m in msgs] == ["first"]
    assert msgs[0]["from_owner"] is True and msgs[0]["created_at"].endswith("Z")
    after = msgs[0]["created_at"]
    assert (
        admin_client.get(f"/api/session/{sid}/updates", params={"after": after}).json()["messages"]
        == []
    )
    await handle_update(ctx(app), bot_id, text_update("second", reply_to=n.telegram_message_id))
    msgs = admin_client.get(f"/api/session/{sid}/updates", params={"after": after}).json()
    assert [m["content"] for m in msgs["messages"]] == ["second"]


def test_updates_unknown_session_and_bad_after(admin_client):
    assert admin_client.get("/api/session/nope/updates").status_code == 404
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    r = admin_client.get(f"/api/session/{sid}/updates", params={"after": "yesterday"})
    assert r.status_code == 422


def test_updates_rate_limited(admin_client):
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    codes = [admin_client.get(f"/api/session/{sid}/updates").status_code for _ in range(21)]
    assert codes[:20] == [200] * 20 and codes[20] == 429
