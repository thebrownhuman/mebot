"""Telegram side of the learning loop: Save to memory, Approve / Edit / Reject, Answer.

* **Save to memory** (under "Sent to ...") cleans the owner's reply into a fact and shows
  it with Approve / Edit / Reject. Nothing is known to the bot until Approve.
* The daily digest and ``/questions`` list open questions with **Answer** buttons; the
  force-reply answer goes through the same cleaning and approval card.

All decisions go through ``mebot.learning.service``, so tapping Approve in Telegram and
in the admin at the same time is a harmless no-op.
"""

import json

from mebot.errors import ApiError
from mebot.learning import service as learning
from mebot.models import LearnedFact, OpenQuestion
from mebot.repos import learned_facts, open_questions
from mebot.telegram.client import TelegramError
from mebot.telegram.events import esc
from mebot.telegram.replies import _answer, _by_id, _by_telegram_id, _payload, _record
from mebot.telegram.updates import Incoming, TgContext, _safe_send

MAX_ANSWER = 1000
BUTTON_LABEL = 28


def _field_label(field: str) -> str:
    return field.replace("_", " ")


def card(fact: LearnedFact) -> tuple[str, dict]:
    """The approval message for a pending fact."""
    text = f"🧠 <b>Save to memory?</b>\n{esc(fact.fact_text, 400)}"
    if fact.suggested_section == "identity" and fact.suggested_field:
        text += (
            f"\n\n<i>Also fills your profile: {_field_label(fact.suggested_field)} = "
            f"{esc(fact.suggested_value, 200)}</i>"
        )
    if fact.needs_review:
        text += (
            "\n\n⚠️ I couldn't rewrite this safely, so it stays close to your own words. "
            "Tap Edit if it needs fixing."
        )
    row = [
        {"text": "Approve", "callback_data": f"fa:{fact.id}"},
        {"text": "Edit", "callback_data": f"fe:{fact.id}"},
        {"text": "Reject", "callback_data": f"fx:{fact.id}"},
    ]
    return text, {"inline_keyboard": [row]}


def _answer_buttons(questions: list[OpenQuestion]) -> dict:
    rows = []
    for q in questions:
        label = (
            q.question if len(q.question) <= BUTTON_LABEL else q.question[: BUTTON_LABEL - 1] + "…"
        )
        rows.append([{"text": f"Answer: {label}", "callback_data": f"oqa:{q.id}"}])
    return {"inline_keyboard": rows}


def open_questions_summary(
    db, bot_id: str, limit: int
) -> tuple[list[OpenQuestion], str, dict | None]:
    """(questions, text lines, Answer buttons) for the digest and /questions."""
    items = open_questions.list_(db, bot_id, "open", limit)
    if not items:
        return [], "", None
    lines = [f"• {esc(q.question, 120)} ({q.ask_count}×)" for q in items]
    return items, "\n".join(lines), _answer_buttons(items)


async def _set_markup(inc: Incoming, cb: dict, label: str) -> None:
    message_id = (cb.get("message") or {}).get("message_id")
    if message_id is None:
        return
    try:
        await inc.client.edit_reply_markup(
            inc.chat_id,
            message_id,
            {"inline_keyboard": [[{"text": label, "callback_data": "noop"}]]},
        )
    except TelegramError:
        pass


async def _send_card(inc: Incoming, fact: LearnedFact) -> None:
    text, markup = card(fact)
    tid = await _safe_send(inc.client, inc.chat_id, text, reply_markup=markup)
    _record(inc, "fact_card", {"fact_id": fact.id}, tid)
    inc.db.commit()


async def _propose_and_show(
    ctx: TgContext, inc: Incoming, *, question: str, answer: str, oq_id: str | None
) -> LearnedFact | None:
    try:
        fact = await learning.propose(
            inc.db,
            inc.bot_id,
            ctx.secret_key,
            question=question,
            answer=answer[:MAX_ANSWER],
            source="telegram",
            open_question_id=oq_id,
        )
    except ApiError as e:
        inc.db.rollback()
        await _safe_send(inc.client, inc.chat_id, f"⚠️ {esc(e.message, 300)}")
        return None
    inc.db.commit()
    await _send_card(inc, fact)
    return fact


def _oq_of_reply(inc: Incoming, record) -> str | None:
    """The open question behind an owner reply (via the ❓ message it answered)."""
    source = _by_id(inc, _payload(record).get("ref", ""), "unanswered")
    return _payload(source).get("open_question_id") if source is not None else None


# --- messages (replies to our force-reply prompts) -------------------------------------


async def on_prompt_reply(ctx: TgContext, inc: Incoming, msg: dict) -> bool:
    replied = (msg.get("reply_to_message") or {}).get("message_id")
    if replied is None:
        return False
    target = _by_telegram_id(inc, replied)
    if target is None or target.kind not in ("fact_edit_prompt", "oq_prompt"):
        return False
    text = (msg.get("text") or "").strip()
    if not text:
        await _safe_send(inc.client, inc.chat_id, "Send your answer as text.")
        return True
    data = _payload(target)
    if target.kind == "fact_edit_prompt":
        try:
            fact = learning.update(inc.db, inc.bot_id, data.get("fact_id", ""), {"fact_text": text})
        except ApiError as e:
            inc.db.rollback()
            await _safe_send(inc.client, inc.chat_id, f"⚠️ {esc(e.message, 300)}")
            return True
        inc.db.commit()
        await _send_card(inc, fact)
        return True
    oq = open_questions.get(inc.db, inc.bot_id, data.get("oq_id", ""))
    if oq is None or oq.status != "open":
        await _safe_send(inc.client, inc.chat_id, "That question is no longer open.")
        return True
    await _propose_and_show(ctx, inc, question=oq.question, answer=text, oq_id=oq.id)
    return True


# --- callbacks -------------------------------------------------------------------------


async def _save_reply(ctx: TgContext, inc: Incoming, cb: dict, nid: str) -> None:
    record = _by_id(inc, nid, "owner_reply")
    if record is None:
        await _answer(inc, cb, "Can't find that answer.")
        return
    p = _payload(record)
    if p.get("fact_id"):  # a second tap must not create a second pending fact
        await _answer(inc, cb, "Already sent for approval above.")
        return
    await _answer(inc, cb, "Cleaning up…")
    question = (p.get("question") or "").strip() or "(question)"
    fact = await _propose_and_show(
        ctx, inc, question=question, answer=p.get("answer", ""), oq_id=_oq_of_reply(inc, record)
    )
    if fact is not None:
        p["fact_id"] = fact.id
        record.payload = json.dumps(p, ensure_ascii=False)
        inc.db.commit()
        await _set_markup(inc, cb, "Sent for approval ↓")


async def _approve(inc: Incoming, cb: dict, fact_id: str, mode: str | None) -> None:
    try:
        learning.approve(inc.db, inc.bot_id, fact_id, mode=mode)
    except ApiError as e:
        inc.db.rollback()
        if e.code == "IDENTITY_FIELD_SET" and e.details:
            d = e.details[0]
            await _answer(inc, cb)
            await _safe_send(
                inc.client,
                inc.chat_id,
                f"{esc(_field_label(d['field']).capitalize())} is already "
                f"<b>{esc(d['current'], 200)}</b>. Replace it with "
                f"<b>{esc(d['new'], 200)}</b>, or keep both?",
                reply_markup={
                    "inline_keyboard": [
                        [
                            {"text": "Replace", "callback_data": f"fm:{fact_id}:r"},
                            {"text": "Keep both", "callback_data": f"fm:{fact_id}:b"},
                        ]
                    ]
                },
            )
            return
        await _answer(inc, cb, e.message[:190])
        return
    inc.db.commit()
    await _set_markup(inc, cb, "Saved ✓")
    await _answer(inc, cb, "Saved to memory")


async def on_callback(ctx: TgContext, inc: Incoming, cb: dict) -> bool:
    action, _, rest = (cb.get("data") or "").partition(":")
    if action == "mem":
        await _save_reply(ctx, inc, cb, rest)
        return True
    if action in ("fa", "fe", "fx", "fm"):
        fact_id, _, arg = rest.partition(":")
        if learned_facts.get(inc.db, inc.bot_id, fact_id) is None:
            await _answer(inc, cb, "That fact no longer exists.")
            return True
        if action == "fa":
            await _approve(inc, cb, fact_id, None)
        elif action == "fm":
            await _approve(inc, cb, fact_id, "replace" if arg == "r" else "keep_both")
        elif action == "fx":
            try:
                learning.reject(inc.db, inc.bot_id, fact_id)
            except ApiError as e:
                inc.db.rollback()
                await _answer(inc, cb, e.message[:190])
                return True
            inc.db.commit()
            await _set_markup(inc, cb, "Rejected ✗")
            await _answer(inc, cb, "Rejected")
        else:  # fe
            tid = await _safe_send(
                inc.client, inc.chat_id, "Send the corrected fact", force_reply=True
            )
            _record(inc, "fact_edit_prompt", {"fact_id": fact_id}, tid)
            inc.db.commit()
            await _answer(inc, cb)
        return True
    if action == "oqa":
        oq = open_questions.get(inc.db, inc.bot_id, rest)
        if oq is None or oq.status != "open":
            await _answer(inc, cb, "That question is no longer open.")
            return True
        tid = await _safe_send(
            inc.client,
            inc.chat_id,
            f"Your answer to: <i>{esc(oq.question, 300)}</i>",
            force_reply=True,
        )
        _record(inc, "oq_prompt", {"oq_id": oq.id}, tid)
        inc.db.commit()
        await _answer(inc, cb)
        return True
    return False


MESSAGE_HANDLERS = [on_prompt_reply]
CALLBACK_HANDLERS = [on_callback]
