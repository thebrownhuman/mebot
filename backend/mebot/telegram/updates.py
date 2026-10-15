"""Incoming Telegram updates (from the poller or the webhook).

Only the linked chat is served. Any other chat gets nothing except the answer to a
``/start <code>`` attempt, so a stranger who finds the bot learns nothing.
"""

import asyncio
import html
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from mebot.models import Bot, utcnow
from mebot.repos import logs
from mebot.telegram import repo
from mebot.telegram.client import TelegramClient, TelegramError

log = logging.getLogger(__name__)

LINK_FAILED = "Link expired or invalid. Generate a new one in mebot admin → Notifications."
COMMANDS = [
    ("status", "Bot status and today's usage"),
    ("today", "Today's activity so far"),
    ("pause", "Pause the chat bot"),
    ("resume", "Resume the chat bot"),
    ("help", "What I can do"),
]
FOREIGN_LOG_EVERY = timedelta(hours=1)


@dataclass
class TgContext:
    session_factory: sessionmaker[Session]
    secret_key: str
    settings: object
    now: Callable[[], datetime] = utcnow
    foreign_logged: dict[tuple[str, str], datetime] = field(default_factory=dict)
    # Outbox pacing: loop time of the last message per chat; sleep is injectable.
    last_sent: dict[str, float] = field(default_factory=dict)
    sleep: Callable = asyncio.sleep


@dataclass
class Incoming:
    """What a handler needs about the current update."""

    db: Session
    row: object
    client: TelegramClient
    chat_id: str
    bot_id: str


def _log_foreign(ctx: TgContext, db: Session, bot_id: str, chat_id: str) -> None:
    now = ctx.now()
    last = ctx.foreign_logged.get((bot_id, chat_id))
    if last is not None and now - last < FOREIGN_LOG_EVERY:
        return
    ctx.foreign_logged[(bot_id, chat_id)] = now
    # The chat id only: never the stranger's text.
    logs.add(db, bot_id, None, "TELEGRAM_FOREIGN_CHAT", detail=f"chat={chat_id}")
    db.commit()


async def _safe_send(client: TelegramClient, chat_id: str, text: str, **kw) -> int | None:
    try:
        return await client.send_message(chat_id, text, **kw)
    except TelegramError as e:
        log.warning("telegram reply failed: %s", e.message)
        return None


async def _start(ctx: TgContext, inc: Incoming, arg: str) -> None:
    row = inc.row
    if arg and repo.consume_link_code(inc.db, row, arg, inc.chat_id, ctx.now()):
        bot = inc.db.get(Bot, inc.bot_id)
        name = bot.name if bot else "mebot"
        logs.add(inc.db, inc.bot_id, None, "telegram_linked")
        inc.db.commit()
        await _safe_send(inc.client, inc.chat_id, f"✅ Linked to <b>{html.escape(name)}</b>.")
        try:
            await inc.client.set_my_commands(COMMANDS)
        except TelegramError as e:
            log.warning("setMyCommands failed: %s", e.message)
        return
    if row.chat_id == inc.chat_id and not arg:
        await _safe_send(inc.client, inc.chat_id, "You're already linked. Send /help.")
        return
    await _safe_send(inc.client, inc.chat_id, LINK_FAILED)


def _handlers() -> tuple[list, list]:
    """Linked-chat handlers, tried in order; each returns True when it handled it."""
    from mebot.telegram import replies  # late import: they build on this module

    return list(replies.MESSAGE_HANDLERS), list(replies.CALLBACK_HANDLERS)


async def handle_update(ctx: TgContext, bot_id: str, update: dict) -> None:
    msg = update.get("message")
    cb = update.get("callback_query")
    chat = (msg or (cb or {}).get("message") or {}).get("chat") or {}
    if "id" not in chat:
        return
    chat_id = str(chat["id"])
    with ctx.session_factory() as db:
        row = repo.get(db, bot_id)
        client = repo.client_for(row, ctx.secret_key)
        if row is None or client is None:
            return
        inc = Incoming(db=db, row=row, client=client, chat_id=chat_id, bot_id=bot_id)
        text = (msg or {}).get("text") or ""
        parts = text.split(maxsplit=1)
        if msg and parts and parts[0].split("@")[0] == "/start":
            await _start(ctx, inc, parts[1].strip() if len(parts) > 1 else "")
            return
        if row.chat_id is None or chat_id != row.chat_id:
            _log_foreign(ctx, db, bot_id, chat_id)
            return
        on_message, on_callback = _handlers()
        handlers = on_message if msg else on_callback
        for h in handlers:
            if await h(ctx, inc, msg or cb):
                return
        if msg:
            await _safe_send(client, chat_id, "I didn't understand that. Send /help.")
        elif cb:
            try:
                await client.answer_callback_query(cb["id"])
            except TelegramError:
                pass
