"""DB-backed notification outbox.

Producers call ``enqueue`` inside the transaction of the event that causes it, so a
notification exists iff the event was committed. ``send_due`` (a background loop)
delivers rows per bot in creation order: a row that must wait (backoff, 429) holds
back the later rows of that bot, so the owner never sees messages out of order.
Each round takes at most PER_BOT_ROUND rows per bot, oldest bots' rows interleaved,
so one tenant's backlog can't starve the others. Inactive tenants are skipped.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from mebot.models import Bot, Notification, new_id, utcnow
from mebot.telegram import repo
from mebot.telegram.client import TelegramError
from mebot.telegram.updates import TgContext

MAX_ATTEMPTS = 6
BASE_DELAY = 5.0  # seconds; doubles per attempt
MAX_DELAY = 3600.0
PER_CHAT_GAP = 1.0  # Telegram: about one message per second per chat
RETENTION = timedelta(days=30)
LIVE = ("pending", "failed")
PER_BOT_ROUND = 5


def enqueue(
    db: Session,
    bot_id: str,
    kind: str,
    payload: dict,
    *,
    session_id: str | None = None,
    ref_message_id: str | None = None,
    nid: str | None = None,
) -> Notification:
    due = utcnow()
    now = due
    # Delivery order is created_at; Windows clocks can repeat a value, so keep it
    # strictly increasing per bot (ids are random and can't break ties in order).
    # Only created_at is bumped: next_attempt_at stays at the real time, otherwise a
    # burst queued in one clock tick would sit "in the future" and block the queue.
    last = db.scalar(select(func.max(Notification.created_at)).where(Notification.bot_id == bot_id))
    if last is not None:
        last = last if last.tzinfo else last.replace(tzinfo=UTC)
        if last >= now:
            now = last + timedelta(microseconds=1)
    n = Notification(
        id=nid or new_id(),
        bot_id=bot_id,
        kind=kind,
        payload=json.dumps(payload, ensure_ascii=False),
        status="pending",
        attempts=0,
        next_attempt_at=due,
        session_id=session_id,
        ref_message_id=ref_message_id,
        created_at=now,
        updated_at=now,
    )
    db.add(n)
    db.flush()
    return n


def payload(n: Notification) -> dict:
    try:
        return json.loads(n.payload)
    except ValueError:
        return {}


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(MAX_DELAY, BASE_DELAY * 2 ** (attempts - 1)))


async def _pace(ctx: TgContext, chat_id: str) -> None:
    clock = ctx.clock or asyncio.get_running_loop().time
    last = ctx.last_sent.get(chat_id)
    if last is not None:
        gap = PER_CHAT_GAP - (clock() - last)
        if gap > 0:
            await ctx.sleep(gap)
    ctx.last_sent[chat_id] = clock()


async def send_due(ctx: TgContext, limit: int = 50) -> int:
    """Deliver due notifications. Returns how many were sent."""
    now = ctx.now()
    sent = 0
    with ctx.session_factory() as db:
        rank = (
            func.row_number()
            .over(
                partition_by=Notification.bot_id,
                order_by=(Notification.created_at, Notification.id),
            )
            .label("rank")
        )
        ranked = (
            select(Notification.id, rank)
            .join(Bot, Bot.id == Notification.bot_id)
            .where(Notification.status.in_(LIVE), Bot.status == "active")
            .subquery()
        )
        live = list(
            db.scalars(
                select(Notification)
                .join(ranked, ranked.c.id == Notification.id)
                .where(ranked.c.rank <= PER_BOT_ROUND)
                .order_by(ranked.c.rank, Notification.created_at, Notification.id)
                .limit(limit)
            )
        )
        blocked: set[str] = set()
        clients: dict[str, tuple] = {}
        for n in live:
            if n.bot_id in blocked:
                continue
            if n.next_attempt_at > now:
                blocked.add(n.bot_id)
                continue
            if n.bot_id not in clients:
                row = repo.get(db, n.bot_id)
                clients[n.bot_id] = (row, repo.client_for(row, ctx.secret_key))
            row, client = clients[n.bot_id]
            if client is None or not row.chat_id or not row.enabled:
                blocked.add(n.bot_id)  # waits until (re)linked
                continue
            data = payload(n)
            await _pace(ctx, row.chat_id)
            try:
                n.telegram_message_id = await client.send_message(
                    row.chat_id,
                    data.get("text", ""),
                    reply_markup=data.get("reply_markup"),
                    force_reply=bool(data.get("force_reply")),
                    reply_to=data.get("reply_to"),
                )
                n.status = "sent"
                n.last_error = None
                sent += 1
            except TelegramError as e:
                _failed(n, e, now)
                blocked.add(n.bot_id)
            n.updated_at = utcnow()
            db.commit()
    return sent


def _failed(n: Notification, e: TelegramError, now: datetime) -> None:
    n.last_error = e.message[:300]  # already scrubbed of the token
    if e.kind == "rate_limit":
        # Telegram told us when to come back; that's not the message's fault.
        n.next_attempt_at = now + timedelta(seconds=e.retry_after or 1)
        return
    n.attempts += 1
    if e.kind == "bad_request" or n.attempts >= MAX_ATTEMPTS:
        n.status = "dead"
        return
    n.status = "failed"
    n.next_attempt_at = now + _backoff(n.attempts)


def purge(db: Session, now: datetime | None = None) -> int:
    cutoff = (now or utcnow()) - RETENTION
    return db.execute(
        delete(Notification).where(
            Notification.status.in_(("sent", "dead")), Notification.updated_at < cutoff
        )
    ).rowcount


def stats(db: Session, bot_id: str) -> dict:
    rows = db.execute(
        select(Notification.status, Notification.updated_at).where(Notification.bot_id == bot_id)
    ).all()
    counts = {"pending": 0, "failed": 0, "dead": 0}
    last_sent = None
    for status, updated in rows:
        if status in counts:
            counts[status] += 1
        elif status == "sent" and (last_sent is None or updated > last_sent):
            last_sent = updated
    return {**counts, "last_sent_at": last_sent}


async def outbox_round(ctx: TgContext) -> None:
    await send_due(ctx)
