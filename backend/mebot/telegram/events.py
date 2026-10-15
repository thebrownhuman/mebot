"""Event → Telegram message. Producers call these inside the event's transaction.

Visitor text is HTML-escaped and truncated; messages never include IPs, profile notes
or the system prompt. Nothing is queued unless Telegram is linked and the toggle is on.
"""

import html
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mebot.models import ChatSession, Contact, Message, TelegramConfig, new_id, utcnow
from mebot.telegram import outbox, repo

MAX_TEXT = 800
LEAK_ALERT_EVERY = timedelta(hours=1)
CAP_WARN_AT = 0.8


def esc(text: str | None, limit: int = MAX_TEXT) -> str:
    text = (text or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text, quote=False)


def zone(row: TelegramConfig) -> ZoneInfo:
    try:
        return ZoneInfo(row.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _active(db: Session, bot_id: str, toggle: str | None = None) -> TelegramConfig | None:
    row = repo.get(db, bot_id)
    if row is None or not row.bot_token_encrypted or not row.chat_id or not row.enabled:
        return None
    if toggle and not getattr(row, toggle):
        return None
    return row


def _name(name: str | None) -> str:
    return esc(name, 80) or "Anonymous"


def new_session(db: Session, bot_id: str, session_id: str, name: str | None) -> None:
    row = _active(db, bot_id, "notify_new_session")
    if row is None:
        return
    local = utcnow().astimezone(zone(row)).strftime("%H:%M")
    outbox.enqueue(
        db,
        bot_id,
        "new_session",
        {"text": f"🟢 New chat — <b>{_name(name)}</b> · {local}"},
        session_id=session_id,
    )


def question(db: Session, bot_id: str, session_id: str, name: str | None, text: str) -> None:
    row = _active(db, bot_id, "notify_every_question")
    if row is None:
        return
    outbox.enqueue(
        db,
        bot_id,
        "question",
        {"text": f"💬 <b>{_name(name)}</b>: {esc(text)}"},
        session_id=session_id,
    )


def unanswered(
    db: Session,
    bot_id: str,
    session_id: str,
    name: str | None,
    text: str,
    ref_message_id: str | None,
    public_url: str | None,
) -> None:
    row = _active(db, bot_id, "notify_unanswered")
    if row is None:
        return
    nid = new_id()
    buttons = [{"text": "Reply", "callback_data": f"reply:{nid}"}]
    if public_url:
        buttons.append(
            {"text": "Open chat", "url": f"{public_url.rstrip('/')}/admin?session={session_id}"}
        )
    outbox.enqueue(
        db,
        bot_id,
        "unanswered",
        {
            "text": f"❓ Unanswered from <b>{_name(name)}</b>:\n{esc(text)}\n\n"
            "<i>Reply to this message to answer them.</i>",
            "reply_markup": {"inline_keyboard": [buttons]},
            # For the reply loop: the visitor's own words and name (raw; escaped on use).
            "question": text[:2000],
            "name": name,
        },
        session_id=session_id,
        ref_message_id=ref_message_id,
        nid=nid,
    )


def contact(db: Session, bot_id: str, c: Contact) -> None:
    row = _active(db, bot_id, "notify_contact")
    if row is None:
        return
    parts = [esc(c.name, 120), esc(c.email, 200)]
    parts += [esc(v, 120) for v in (c.company, c.role) if v]
    text = "📇 Contact left — " + ", ".join(parts)
    if c.note:
        text += f"\n{esc(c.note)}"
    outbox.enqueue(db, bot_id, "contact", {"text": text}, session_id=c.session_id)


def paused(db: Session, bot_id: str, is_paused: bool) -> None:
    row = _active(db, bot_id, "notify_limits")
    if row is None:
        return
    text = (
        "⏸️ The bot is <b>paused</b>. Visitors can't chat. Send /resume to turn it back on."
        if is_paused
        else "▶️ The bot is <b>running</b> again."
    )
    outbox.enqueue(db, bot_id, "limits", {"text": text})


def cap_warning(db: Session, bot_id: str, used: int, cap: int, day: date) -> None:
    """At most once per UTC day, when >= 80% of the daily message cap is used."""
    if cap <= 0 or used < cap * CAP_WARN_AT:
        return
    row = _active(db, bot_id, "notify_limits")
    if row is None or row.last_cap_alert_date == day.isoformat():
        return
    row.last_cap_alert_date = day.isoformat()
    pct = min(100, int(used * 100 / cap))
    outbox.enqueue(
        db,
        bot_id,
        "limits",
        {"text": f"⚠️ {pct}% of today's message cap used ({used}/{cap})."},
    )


def leak_blocked(db: Session, bot_id: str, now: datetime | None = None) -> None:
    now = now or utcnow()
    row = _active(db, bot_id, "notify_limits")
    if row is None:
        return
    if row.last_leak_alert_at is not None and now - row.last_leak_alert_at < LEAK_ALERT_EVERY:
        return
    row.last_leak_alert_at = now
    outbox.enqueue(
        db,
        bot_id,
        "limits",
        {"text": "🛡️ A reply was blocked because it looked like a prompt leak."},
    )


# --- digest / today -------------------------------------------------------------------


def _local_day_bounds(tz: ZoneInfo, local_day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(local_day, time.min, tz).astimezone(UTC)
    end = datetime.combine(local_day + timedelta(days=1), time.min, tz).astimezone(UTC)
    return start, end


def activity(db: Session, bot_id: str, start: datetime, end: datetime) -> dict:
    chats = db.scalar(
        select(func.count())
        .select_from(ChatSession)
        .where(
            ChatSession.bot_id == bot_id,
            ChatSession.started_at >= start,
            ChatSession.started_at < end,
        )
    )
    msgs = db.execute(
        select(Message.role, Message.content, Message.unanswered).where(
            Message.bot_id == bot_id, Message.created_at >= start, Message.created_at < end
        )
    ).all()
    questions = [c for r, c, _ in msgs if r == "user"]
    contacts = db.scalar(
        select(func.count())
        .select_from(Contact)
        .where(
            Contact.bot_id == bot_id,
            Contact.deleted_at.is_(None),
            Contact.created_at >= start,
            Contact.created_at < end,
        )
    )
    top = Counter(" ".join(q.lower().split())[:120] for q in questions).most_common(3)
    return {
        "chats": chats or 0,
        "messages": len(questions),
        "unanswered": sum(1 for r, _, u in msgs if r == "assistant" and u),
        "contacts": contacts or 0,
        "top": top,
    }


def summary_text(title: str, a: dict) -> str:
    lines = [
        f"<b>{title}</b>",
        f"Chats: {a['chats']} · Messages: {a['messages']}",
        f"Unanswered: {a['unanswered']} · Contacts: {a['contacts']}",
    ]
    if a["top"]:
        lines.append("Top questions:")
        lines += [f"• {esc(q, 120)} ({n})" for q, n in a["top"]]
    return "\n".join(lines)


def today_so_far(db: Session, row: TelegramConfig, now: datetime | None = None) -> str:
    tz = zone(row)
    local = (now or utcnow()).astimezone(tz)
    start, _ = _local_day_bounds(tz, local.date())
    return summary_text(
        f"📊 Today so far ({local.date().isoformat()})",
        activity(db, row.bot_id, start, now or utcnow()),
    )


def maybe_digest(db: Session, row: TelegramConfig, now: datetime) -> bool:
    """Queue the daily digest once per owner-local date, at/after digest_hour.
    Zero-activity days are skipped (but still marked done)."""
    if not row.daily_digest or not row.chat_id or not row.bot_token_encrypted:
        return False
    tz = zone(row)
    local = now.astimezone(tz)
    today = local.date().isoformat()
    if local.hour < row.digest_hour or row.last_digest_date == today:
        return False
    row.last_digest_date = today
    start, end = _local_day_bounds(tz, local.date())
    a = activity(db, row.bot_id, start, min(end, now))
    if not (a["chats"] or a["messages"] or a["contacts"]):
        return False
    outbox.enqueue(
        db, row.bot_id, "daily_digest", {"text": summary_text(f"🗓️ Daily digest — {today}", a)}
    )
    return True


async def digest_round(ctx) -> None:
    now = ctx.now()
    with ctx.session_factory() as db:
        for row in repo.all_configured(db):
            maybe_digest(db, row, now)
        db.commit()
