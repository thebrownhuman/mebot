"""Reply-back loop: the owner answers an unanswered question from Telegram.

Tap **Reply** (force-reply prompt) or reply directly to the ❓ message; either way the
replied-to Telegram message id maps to an outbox row, hence to the session and the
visitor's question. The answer is stored as an assistant message with from_owner=true
(the recruiter UI polls for it), and **Save to FAQ** turns it into a FAQ entry once.
"""

import json

from sqlalchemy import select

from mebot.models import Notification, utcnow
from mebot.profile.schemas import FaqIn
from mebot.profile.sections import SECTIONS
from mebot.repos import logs, sessions
from mebot.repos import profile_items as profile
from mebot.telegram.client import TelegramError
from mebot.telegram.events import esc
from mebot.telegram.updates import Incoming, TgContext, _safe_send

NO_MATCH = "Can't match this to a chat. Reply to a ❓ Unanswered message."
MAX_ANSWER = 4000


def _payload(n: Notification) -> dict:
    try:
        return json.loads(n.payload)
    except ValueError:
        return {}


def _by_telegram_id(inc: Incoming, message_id: int) -> Notification | None:
    return inc.db.scalar(
        select(Notification).where(
            Notification.bot_id == inc.bot_id, Notification.telegram_message_id == message_id
        )
    )


def _by_id(inc: Incoming, nid: str, kind: str) -> Notification | None:
    n = inc.db.get(Notification, nid)
    return n if n is not None and n.bot_id == inc.bot_id and n.kind == kind else None


def _record(inc: Incoming, kind: str, payload: dict, telegram_id: int | None, **kw) -> Notification:
    """A message we already sent directly (not via the outbox), kept for mapping."""
    now = utcnow()
    n = Notification(
        bot_id=inc.bot_id,
        kind=kind,
        payload=json.dumps(payload, ensure_ascii=False),
        status="sent",
        attempts=0,
        next_attempt_at=now,
        telegram_message_id=telegram_id,
        created_at=now,
        updated_at=now,
        **kw,
    )
    inc.db.add(n)
    inc.db.flush()
    return n


async def on_reply_message(ctx: TgContext, inc: Incoming, msg: dict) -> bool:
    replied = (msg.get("reply_to_message") or {}).get("message_id")
    if replied is None:
        return False
    answer = (msg.get("text") or "").strip()
    target = _by_telegram_id(inc, replied)
    if target is not None and target.kind == "reply_prompt":
        target = _by_id(inc, _payload(target).get("ref", ""), "unanswered")
    if (
        target is None
        or target.kind != "unanswered"
        or not target.session_id
        or sessions.get(inc.db, inc.bot_id, target.session_id) is None
    ):
        await _safe_send(inc.client, inc.chat_id, NO_MATCH)
        return True
    if not answer:
        await _safe_send(inc.client, inc.chat_id, "Send your answer as text.")
        return True
    answer = answer[:MAX_ANSWER]
    data = _payload(target)
    sessions.add_message(
        inc.db, inc.bot_id, target.session_id, "assistant", answer, from_owner=True
    )
    logs.add(inc.db, inc.bot_id, target.session_id, "OWNER_REPLIED")
    record = _record(
        inc,
        "owner_reply",
        {"question": data.get("question", ""), "answer": answer, "ref": target.id},
        None,
        session_id=target.session_id,
    )
    inc.db.commit()
    name = esc(data.get("name"), 80) or "the visitor"
    tid = await _safe_send(
        inc.client,
        inc.chat_id,
        f"✅ Sent to <b>{name}</b>.",
        reply_markup={
            "inline_keyboard": [[{"text": "Save to FAQ", "callback_data": f"faq:{record.id}"}]]
        },
    )
    record.telegram_message_id = tid
    inc.db.commit()
    return True


async def _answer(inc: Incoming, cb: dict, text: str | None = None) -> None:
    try:
        await inc.client.answer_callback_query(cb["id"], text)
    except TelegramError:
        pass


async def on_callback(ctx: TgContext, inc: Incoming, cb: dict) -> bool:
    data = cb.get("data") or ""
    action, _, nid = data.partition(":")
    if action == "reply":
        target = _by_id(inc, nid, "unanswered")
        if target is None:
            await _answer(inc, cb, "That question is no longer available.")
            return True
        question = esc(_payload(target).get("question"), 300)
        tid = await _safe_send(
            inc.client, inc.chat_id, f"Your answer to: <i>{question}</i>", force_reply=True
        )
        _record(inc, "reply_prompt", {"ref": target.id}, tid, session_id=target.session_id)
        inc.db.commit()
        await _answer(inc, cb)
        return True
    if action == "faq":
        record = _by_id(inc, nid, "owner_reply")
        if record is None:
            await _answer(inc, cb, "Can't find that answer.")
            return True
        p = _payload(record)
        if not p.get("faq_id"):
            question = (p.get("question") or "").strip()[:400] or "(question)"
            faq = profile.create(
                inc.db,
                SECTIONS["faqs"],
                inc.bot_id,
                FaqIn(question=question, answer=p.get("answer", "")[:4000]),
            )
            p["faq_id"] = faq.id
            record.payload = json.dumps(p, ensure_ascii=False)
            logs.add(inc.db, inc.bot_id, record.session_id, "profile_updated", detail="faqs")
            inc.db.commit()
        message_id = (cb.get("message") or {}).get("message_id")
        if message_id is not None:
            try:
                await inc.client.edit_reply_markup(
                    inc.chat_id,
                    message_id,
                    {"inline_keyboard": [[{"text": "Saved ✓", "callback_data": "noop"}]]},
                )
            except TelegramError:
                pass
        await _answer(inc, cb, "Saved to FAQ")
        return True
    if action == "noop":
        await _answer(inc, cb)
        return True
    return False


MESSAGE_HANDLERS = [on_reply_message]
CALLBACK_HANDLERS = [on_callback]
