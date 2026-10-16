import json
from datetime import UTC, datetime

import respx
from sqlalchemy import select

from mebot.models import LearnedFact, Notification, OpenQuestion
from mebot.profile.data import load_profile
from mebot.profile.schemas import IdentityIn
from mebot.repos import bots, open_questions
from mebot.repos import profile_items as profile
from mebot.telegram import events
from mebot.telegram.updates import handle_update
from tests.test_telegram_replies import unanswered_sent
from tests.tg_helpers import (
    callback_update,
    ctx,
    link,
    mock_telegram,
    sent,
    sent_texts,
    text_update,
)

FACT = "Shivansh lives in Bangalore and is open to remote work."


def cleaned(fake_llm, **over):
    out = {
        "fact_text": FACT,
        "section": "learned",
        "field": None,
        "value": None,
        "personal_only": False,
    }
    out.update(over)
    fake_llm.chunks = [json.dumps(out)]


def buttons(routes):
    return [b for row in sent(routes)[-1]["reply_markup"]["inline_keyboard"] for b in row]


def facts(app):
    with app.state.session_factory() as db:
        return list(db.scalars(select(LearnedFact)))


def groups(app):
    with app.state.session_factory() as db:
        return list(db.scalars(select(OpenQuestion)))


async def reply_and_get_save_cb(admin_client, app, fake_llm, routes, answer="Bangalore, remote ok"):
    bot_id, sid, n = await unanswered_sent(admin_client, app, fake_llm, "Where does he live?")
    await handle_update(ctx(app), bot_id, text_update(answer, reply_to=n.telegram_message_id))
    [save] = buttons(routes)
    assert save["text"] == "Save to memory" and save["callback_data"].startswith("mem:")
    return bot_id, sid, save["callback_data"]


@respx.mock
async def test_save_to_memory_shows_card_with_approve_edit_reject(admin_client, app, fake_llm):
    routes = mock_telegram()
    bot_id, sid, save = await reply_and_get_save_cb(admin_client, app, fake_llm, routes)
    cleaned(fake_llm)
    await handle_update(ctx(app), bot_id, callback_update(save, message_id=500))
    card = sent(routes)[-1]
    assert card["text"].startswith("🧠 <b>Save to memory?</b>\n" + FACT)
    assert [b["text"] for b in buttons(routes)] == ["Approve", "Edit", "Reject"]
    [fact] = facts(app)
    assert fact.status == "pending" and fact.source == "telegram"
    assert fact.answer_raw == "Bangalore, remote ok" and fact.question == "Where does he live?"
    with app.state.session_factory() as db:
        assert load_profile(db, bot_id).learned == []  # nothing known until Approve
    assert (
        json.loads(routes["editMessageReplyMarkup"].calls.last.request.content)["message_id"] == 500
    )


@respx.mock
async def test_second_save_tap_does_not_duplicate(admin_client, app, fake_llm):
    routes = mock_telegram()
    bot_id, sid, save = await reply_and_get_save_cb(admin_client, app, fake_llm, routes)
    cleaned(fake_llm)
    for _ in range(3):
        await handle_update(ctx(app), bot_id, callback_update(save))
    assert len(facts(app)) == 1
    assert json.loads(routes["answerCallbackQuery"].calls.last.request.content)["text"] == (
        "Already sent for approval above."
    )


@respx.mock
async def test_approve_links_open_question_and_is_idempotent(admin_client, app, fake_llm):
    routes = mock_telegram()
    bot_id, sid, save = await reply_and_get_save_cb(admin_client, app, fake_llm, routes)
    cleaned(fake_llm)
    await handle_update(ctx(app), bot_id, callback_update(save))
    [approve, _edit, _reject] = buttons(routes)
    for _ in range(2):
        await handle_update(ctx(app), bot_id, callback_update(approve["callback_data"], 600))
    [fact] = facts(app)
    assert fact.status == "approved" and fact.open_question_id
    [group] = groups(app)
    assert group.status == "answered" and group.answered_fact_id == fact.id
    with app.state.session_factory() as db:
        assert load_profile(db, bot_id).learned == [FACT]
    edit = json.loads(routes["editMessageReplyMarkup"].calls.last.request.content)
    assert edit["reply_markup"]["inline_keyboard"][0][0]["text"] == "Saved ✓"


@respx.mock
async def test_reject_reopens_question(admin_client, app, fake_llm):
    routes = mock_telegram()
    bot_id, sid, save = await reply_and_get_save_cb(admin_client, app, fake_llm, routes)
    cleaned(fake_llm)
    await handle_update(ctx(app), bot_id, callback_update(save))
    [_a, _e, reject] = buttons(routes)
    await handle_update(ctx(app), bot_id, callback_update(reject["callback_data"], 601))
    assert facts(app)[0].status == "rejected" and groups(app)[0].status == "open"
    edit = json.loads(routes["editMessageReplyMarkup"].calls.last.request.content)
    assert edit["reply_markup"]["inline_keyboard"][0][0]["text"] == "Rejected ✗"
    # a late Approve (e.g. double-tap from an old card) cannot resurrect it
    await handle_update(ctx(app), bot_id, callback_update(_a["callback_data"]))
    assert facts(app)[0].status == "rejected"


@respx.mock
async def test_edit_flow_force_reply_then_new_card(admin_client, app, fake_llm):
    routes = mock_telegram()
    bot_id, sid, save = await reply_and_get_save_cb(admin_client, app, fake_llm, routes)
    cleaned(fake_llm)
    await handle_update(ctx(app), bot_id, callback_update(save))
    [_a, edit_btn, _r] = buttons(routes)
    await handle_update(ctx(app), bot_id, callback_update(edit_btn["callback_data"]))
    prompt = sent(routes)[-1]
    assert prompt["text"] == "Send the corrected fact" and prompt["reply_markup"] == {
        "force_reply": True
    }
    prompt_id = int(routes["sendMessage"].calls.last.response.json()["result"]["message_id"])
    await handle_update(
        ctx(app), bot_id, text_update("Shivansh is based in Bangalore.", reply_to=prompt_id)
    )
    assert facts(app)[0].fact_text == "Shivansh is based in Bangalore."
    assert "Shivansh is based in Bangalore." in sent(routes)[-1]["text"]
    assert [b["text"] for b in buttons(routes)] == ["Approve", "Edit", "Reject"]


@respx.mock
async def test_edit_with_personal_text_is_refused(admin_client, app, fake_llm):
    routes = mock_telegram()
    bot_id, sid, save = await reply_and_get_save_cb(admin_client, app, fake_llm, routes)
    cleaned(fake_llm)
    await handle_update(ctx(app), bot_id, callback_update(save))
    [_a, edit_btn, _r] = buttons(routes)
    await handle_update(ctx(app), bot_id, callback_update(edit_btn["callback_data"]))
    prompt_id = int(routes["sendMessage"].calls.last.response.json()["result"]["message_id"])
    await handle_update(ctx(app), bot_id, text_update("He is married.", reply_to=prompt_id))
    assert sent_texts(routes)[-1].startswith("⚠️ That answer is about a personal topic")
    assert facts(app)[0].fact_text == FACT


@respx.mock
async def test_personal_owner_answer_is_not_saved(admin_client, app, fake_llm):
    routes = mock_telegram()
    bot_id, sid, save = await reply_and_get_save_cb(
        admin_client, app, fake_llm, routes, answer="He is single"
    )
    cleaned(fake_llm, fact_text="", personal_only=True)
    await handle_update(ctx(app), bot_id, callback_update(save))
    assert sent_texts(routes)[-1].startswith("⚠️ That answer is about a personal topic")
    assert facts(app) == []


@respx.mock
async def test_identity_set_asks_replace_or_keep_both(admin_client, app, fake_llm):
    routes = mock_telegram()
    bot_id, sid, save = await reply_and_get_save_cb(
        admin_client, app, fake_llm, routes, "Bangalore"
    )
    with app.state.session_factory() as db:
        profile.put_identity(db, bot_id, IdentityIn(full_name="Shivansh", location="Pune"))
        db.commit()
    cleaned(fake_llm, section="identity", field="location", value="Bangalore")
    await handle_update(ctx(app), bot_id, callback_update(save))
    assert "Also fills your profile: location = Bangalore" in sent(routes)[-1]["text"]
    [approve, _e, _r] = buttons(routes)
    await handle_update(ctx(app), bot_id, callback_update(approve["callback_data"]))
    ask = sent(routes)[-1]
    assert "Location is already <b>Pune</b>" in ask["text"] and "<b>Bangalore</b>" in ask["text"]
    assert [b["text"] for b in buttons(routes)] == ["Replace", "Keep both"]
    assert facts(app)[0].status == "pending"
    replace = buttons(routes)[0]["callback_data"]
    assert len(replace) <= 64
    await handle_update(ctx(app), bot_id, callback_update(replace))
    with app.state.session_factory() as db:
        assert profile.get_identity(db, bot_id).location == "Bangalore"
    assert facts(app)[0].status == "approved"


@respx.mock
async def test_keep_both_button(admin_client, app, fake_llm):
    routes = mock_telegram()
    bot_id, sid, save = await reply_and_get_save_cb(
        admin_client, app, fake_llm, routes, "Bangalore"
    )
    with app.state.session_factory() as db:
        profile.put_identity(db, bot_id, IdentityIn(full_name="Shivansh", location="Pune"))
        db.commit()
    cleaned(fake_llm, section="identity", field="location", value="Bangalore")
    await handle_update(ctx(app), bot_id, callback_update(save))
    await handle_update(ctx(app), bot_id, callback_update(buttons(routes)[0]["callback_data"]))
    await handle_update(ctx(app), bot_id, callback_update(buttons(routes)[1]["callback_data"]))
    with app.state.session_factory() as db:
        assert profile.get_identity(db, bot_id).location == "Pune"
        assert load_profile(db, bot_id).learned == [FACT]


@respx.mock
async def test_stale_fact_callback(admin_client, app, fake_llm):
    routes = mock_telegram()
    bot_id = link(app)
    await handle_update(ctx(app), bot_id, callback_update("fa:does-not-exist"))
    assert json.loads(routes["answerCallbackQuery"].calls.last.request.content)["text"] == (
        "That fact no longer exists."
    )


# --- open questions: /questions, digest, Answer buttons ------------------------------------


def seed_questions(app, bot_id):
    with app.state.session_factory() as db:
        for text, times in (("What is his visa status", 4), ("Does he drive", 1), ("Shoe size", 2)):
            for _ in range(times):
                open_questions.record(db, bot_id, text, "s")
        db.commit()


@respx.mock
async def test_questions_command_lists_top_with_answer_buttons(admin_client, app):
    routes = mock_telegram()
    bot_id = link(app)
    await handle_update(ctx(app), bot_id, text_update("/questions"))
    assert sent_texts(routes)[-1] == "No open questions right now. 🎉"
    seed_questions(app, bot_id)
    await handle_update(ctx(app), bot_id, text_update("/questions"))
    msg = sent(routes)[-1]
    lines = msg["text"].splitlines()
    assert lines[1].startswith("• What is his visa status (4×)")
    assert [b["text"] for b in buttons(routes)][0] == "Answer: What is his visa status"
    assert len(buttons(routes)) == 3 and all(len(b["callback_data"]) <= 64 for b in buttons(routes))


@respx.mock
async def test_answer_button_force_reply_then_card(admin_client, app, fake_llm):
    routes = mock_telegram()
    bot_id = link(app)
    seed_questions(app, bot_id)
    await handle_update(ctx(app), bot_id, text_update("/questions"))
    answer_btn = buttons(routes)[0]["callback_data"]
    await handle_update(ctx(app), bot_id, callback_update(answer_btn))
    prompt = sent(routes)[-1]
    assert prompt["text"] == "Your answer to: <i>What is his visa status</i>"
    assert prompt["reply_markup"] == {"force_reply": True}
    prompt_id = int(routes["sendMessage"].calls.last.response.json()["result"]["message_id"])
    cleaned(fake_llm, fact_text="Shivansh needs no visa to work in India.")
    await handle_update(ctx(app), bot_id, text_update("No visa needed", reply_to=prompt_id))
    assert sent(routes)[-1]["text"].startswith("🧠 <b>Save to memory?</b>")
    [fact] = facts(app)
    assert fact.question == "What is his visa status" and fact.source == "telegram"
    [approve, _e, _r] = buttons(routes)
    await handle_update(ctx(app), bot_id, callback_update(approve["callback_data"]))
    with app.state.session_factory() as db:
        top = open_questions.list_(db, bot_id, "answered")
        assert [q.question for q in top] == ["What is his visa status"]


@respx.mock
async def test_answer_button_for_closed_question(admin_client, app):
    routes = mock_telegram()
    bot_id = link(app)
    seed_questions(app, bot_id)
    with app.state.session_factory() as db:
        q = open_questions.list_(db, bot_id)[0]
        open_questions.set_status(db, q, "dismissed")
        db.commit()
        qid = q.id
    await handle_update(ctx(app), bot_id, callback_update(f"oqa:{qid}"))
    assert json.loads(routes["answerCallbackQuery"].calls.last.request.content)["text"] == (
        "That question is no longer open."
    )


def test_digest_lists_top_three_open_questions_with_buttons(admin_client, app):
    from datetime import timedelta

    bot_id = link(app, daily_digest=True, digest_hour=0, timezone="UTC")
    seed_questions(app, bot_id)
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    assert sid
    with app.state.session_factory() as db:
        from mebot.telegram import repo

        row = repo.get(db, bot_id)
        now = datetime.now(UTC) + timedelta(minutes=1)
        assert events.maybe_digest(db, row, now)
        db.commit()
        [n] = list(db.scalars(select(Notification).where(Notification.kind == "daily_digest")))
    data = json.loads(n.payload)
    assert "Open questions (top 3):" in data["text"]
    assert "• What is his visa status (4×)" in data["text"]
    rows = data["reply_markup"]["inline_keyboard"]
    assert len(rows) == 3 and rows[0][0]["callback_data"].startswith("oqa:")


def test_digest_without_open_questions_has_no_buttons(admin_client, app):
    from datetime import timedelta

    bot_id = link(app, daily_digest=True, digest_hour=0, timezone="UTC")
    admin_client.post("/api/session", json={})
    with app.state.session_factory() as db:
        from mebot.telegram import repo

        row = repo.get(db, bot_id)
        assert events.maybe_digest(db, row, datetime.now(UTC) + timedelta(minutes=1))
        [n] = list(db.scalars(select(Notification).where(Notification.kind == "daily_digest")))
    assert "reply_markup" not in json.loads(n.payload)
    assert "Open questions" not in json.loads(n.payload)["text"]


def test_bots_helper_import():
    assert bots and callable(bots.get_primary)
