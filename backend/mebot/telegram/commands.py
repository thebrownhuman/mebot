"""Commands from the linked chat: /status /pause /resume /today /help."""

from mebot.limits import counters
from mebot.repos import limits as limits_repo
from mebot.repos import logs
from mebot.telegram import events
from mebot.telegram.updates import COMMANDS, Incoming, TgContext, _safe_send

HELP = "\n".join(["<b>mebot commands</b>"] + [f"/{c} — {d}" for c, d in COMMANDS])


def _status(inc: Incoming, ctx: TgContext) -> str:
    limits = limits_repo.get_or_create(inc.db, inc.bot_id)
    now = ctx.now()
    row = counters.get(inc.db, inc.bot_id, "bot_day", "*", now.date())
    used = row.messages if row else 0
    state = "⏸️ paused" if limits.paused else "🟢 running"
    tokens = f"\nTokens today: {row.tokens if row else 0}" if limits.daily_token_cap else ""
    return (
        f"<b>Status:</b> {state}\n"
        f"Messages today (UTC): {used}/{limits.daily_message_cap}{tokens}\n\n"
        + events.today_so_far(inc.db, inc.row, now)
    )


def _set_paused(inc: Incoming, paused: bool) -> str:
    limits = limits_repo.get_or_create(inc.db, inc.bot_id)
    if limits.paused == paused:
        return "Already paused." if paused else "Already running."
    limits_repo.update(inc.db, limits, {"paused": paused})
    logs.add(inc.db, inc.bot_id, None, "limits_updated", detail="paused (telegram)")
    inc.db.commit()
    if paused:
        return "⏸️ Paused. Visitors see the paused message; no AI calls are made. /resume to undo."
    return "▶️ Resumed. Visitors can chat again."


async def on_command(ctx: TgContext, inc: Incoming, msg: dict) -> bool:
    text = (msg.get("text") or "").strip()
    if not text.startswith("/"):
        return False
    cmd = text.split(maxsplit=1)[0][1:].split("@")[0].lower()
    if cmd == "status":
        reply = _status(inc, ctx)
    elif cmd == "pause":
        reply = _set_paused(inc, True)
    elif cmd == "resume":
        reply = _set_paused(inc, False)
    elif cmd == "today":
        reply = events.today_so_far(inc.db, inc.row, ctx.now())
    elif cmd == "help":
        reply = HELP
    else:
        reply = "Unknown command. " + HELP
    await _safe_send(inc.client, inc.chat_id, reply)
    return True
