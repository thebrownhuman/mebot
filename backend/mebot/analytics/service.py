"""Dashboard numbers, computed from sessions / messages / access_log in the bot's timezone.

Everything takes ``now`` so tests can freeze the clock. A range is whole *local* days
ending today (``7d`` = today and the six days before); the previous range is the same
number of local days just before it. Day edges are local midnights converted to UTC, so
a DST change makes a 23- or 25-hour day without any special case.
"""

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mebot import tz as tzmod
from mebot.analytics import cache
from mebot.guard import personal
from mebot.models import (
    AccessLog,
    Bot,
    ChatSession,
    Contact,
    Message,
    UsageCounter,
    WidgetSettings,
    utcnow,
)
from mebot.repos import limits as limits_repo
from mebot.repos import llm_configs, open_questions
from mebot.repos import widget as widget_repo

RANGES = {"7d": 7, "30d": 30, "90d": 90}
DIRECT = "direct"
TOP_N = 10
MAX_DISTINCT = 2000  # distinct normalised questions compared for grouping
MAX_EXAMPLE = 200


@dataclass(frozen=True)
class Window:
    zone: ZoneInfo
    days: list[date]  # local days of the current range, oldest first
    start: datetime  # UTC, inclusive
    end: datetime  # UTC, exclusive
    prev_start: datetime
    bounds: list[datetime]  # UTC start of each local day (+ end), for bucketing

    def bucket(self, ts: datetime) -> int | None:
        i = bisect_right(self.bounds, ts) - 1
        return i if 0 <= i < len(self.days) else None


def _midnight(zone: ZoneInfo, day: date) -> datetime:
    return datetime.combine(day, time.min, zone).astimezone(UTC)


def window(zone: ZoneInfo, range_key: str, now: datetime) -> Window:
    n = RANGES[range_key]
    today = now.astimezone(zone).date()
    days = [today - timedelta(days=n - 1 - i) for i in range(n)]
    bounds = [_midnight(zone, d) for d in days] + [_midnight(zone, today + timedelta(days=1))]
    return Window(
        zone=zone,
        days=days,
        start=bounds[0],
        end=bounds[-1],
        prev_start=_midnight(zone, days[0] - timedelta(days=n)),
        bounds=bounds,
    )


# --- building blocks --------------------------------------------------------------------


def _chat_ids(db: Session, bot_id: str, start: datetime, end: datetime) -> dict[str, datetime]:
    """Sessions started in [start, end) with at least one visitor message -> started_at."""
    rows = db.execute(
        select(ChatSession.id, ChatSession.started_at)
        .where(
            ChatSession.bot_id == bot_id,
            ChatSession.started_at >= start,
            ChatSession.started_at < end,
            select(Message.id)
            .where(Message.session_id == ChatSession.id, Message.role == "user")
            .exists(),
        )
        .order_by(ChatSession.started_at)
    )
    return {sid: ts for sid, ts in rows}


def _msg_counts(db: Session, bot_id: str, start: datetime, end: datetime) -> dict[str, int]:
    base = (Message.bot_id == bot_id, Message.created_at >= start, Message.created_at < end)
    visitor = db.scalar(
        select(func.count()).select_from(Message).where(*base, Message.role == "user")
    )
    replies = db.scalar(
        select(func.count())
        .select_from(Message)
        .where(*base, Message.role == "assistant", Message.from_owner.is_(False))
    )
    unanswered = db.scalar(
        select(func.count())
        .select_from(Message)
        .where(
            *base,
            Message.role == "assistant",
            Message.from_owner.is_(False),
            Message.unanswered.is_(True),
        )
    )
    owner = db.scalar(
        select(func.count()).select_from(Message).where(*base, Message.from_owner.is_(True))
    )
    return {
        "visitor": visitor or 0,
        "replies": replies or 0,
        "unanswered": unanswered or 0,
        "owner": owner or 0,
    }


def _contacts(db: Session, bot_id: str, start: datetime, end: datetime) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Contact)
            .where(
                Contact.bot_id == bot_id,
                Contact.deleted_at.is_(None),
                Contact.created_at >= start,
                Contact.created_at < end,
            )
        )
        or 0
    )


def _tokens(db: Session, bot_id: str, first: date, last: date) -> tuple[int, bool]:
    """Tokens from the daily counters (kept ~7 days, so older ranges are partial)."""
    rows = db.execute(
        select(func.sum(UsageCounter.tokens), func.sum(UsageCounter.estimated_tokens)).where(
            UsageCounter.bot_id == bot_id,
            UsageCounter.scope == "bot_day",
            UsageCounter.window_start >= first.isoformat(),
            UsageCounter.window_start <= last.isoformat(),
        )
    ).one()
    return int(rows[0] or 0), bool(rows[1])


def _kpis_for(db: Session, bot_id: str, start: datetime, end: datetime, zone: ZoneInfo) -> dict:
    chats = len(_chat_ids(db, bot_id, start, end))
    m = _msg_counts(db, bot_id, start, end)
    tokens, estimated = _tokens(
        db,
        bot_id,
        start.astimezone(zone).date(),
        (end - timedelta(seconds=1)).astimezone(zone).date(),
    )
    return {
        "chats": chats,
        "visitor_messages": m["visitor"],
        "avg_messages_per_chat": round(m["visitor"] / chats, 2) if chats else None,
        "unanswered_rate": round(m["unanswered"] / m["replies"], 4) if m["replies"] else None,
        "contacts": _contacts(db, bot_id, start, end),
        "owner_replies": m["owner"],
        "tokens": tokens,
        "tokens_estimated": estimated,
    }


def kpis(db: Session, bot_id: str, w: Window) -> dict:
    cur = _kpis_for(db, bot_id, w.start, w.end, w.zone)
    prev = _kpis_for(db, bot_id, w.prev_start, w.start, w.zone)
    out = {k: {"value": v, "previous": prev[k]} for k, v in cur.items() if k != "tokens_estimated"}
    out["tokens"]["estimated"] = cur["tokens_estimated"]
    # A live count, not a per-range number: no previous period.
    out["open_questions"] = {"value": open_questions.count_open(db, bot_id), "previous": None}
    return out


def series(db: Session, bot_id: str, w: Window) -> list[dict]:
    out = [
        {"date": d.isoformat(), "chats": 0, "visitor_messages": 0, "unanswered": 0} for d in w.days
    ]
    for ts in _chat_ids(db, bot_id, w.start, w.end).values():
        i = w.bucket(ts)
        if i is not None:
            out[i]["chats"] += 1
    rows = db.execute(
        select(Message.created_at, Message.role, Message.unanswered, Message.from_owner).where(
            Message.bot_id == bot_id, Message.created_at >= w.start, Message.created_at < w.end
        )
    )
    for ts, role, unanswered, from_owner in rows:
        i = w.bucket(ts)
        if i is None:
            continue
        if role == "user":
            out[i]["visitor_messages"] += 1
        elif unanswered and not from_owner:
            out[i]["unanswered"] += 1
    return out


def top_questions(db: Session, bot_id: str, w: Window, limit: int = TOP_N) -> list[dict]:
    """Visitor questions grouped like open questions (same normaliser, Jaccard >= 0.6).
    Personal-looking messages are excluded: they never reach the owner."""
    rows = db.execute(
        select(Message.content).where(
            Message.bot_id == bot_id,
            Message.role == "user",
            Message.created_at >= w.start,
            Message.created_at < w.end,
        )
    ).scalars()
    exact: dict[str, dict] = {}
    for content in rows:
        text = " ".join((content or "").split())
        if not text or personal.classify(text) is not None:
            continue
        key = open_questions.normalize(text) or open_questions._words(text)
        slot = exact.get(key)
        if slot is None:
            exact[key] = {"count": 1, "example": text[:MAX_EXAMPLE]}
        else:
            slot["count"] += 1
    # Most asked first, so a group's example is its most common wording.
    ordered = sorted(exact.items(), key=lambda kv: (-kv[1]["count"], kv[0]))[:MAX_DISTINCT]
    groups: list[dict] = []
    for key, slot in ordered:
        for g in groups:
            if open_questions.similarity(g["key"], key) >= open_questions.SIMILARITY:
                g["count"] += slot["count"]
                break
        else:
            groups.append({"key": key, "count": slot["count"], "example": slot["example"]})
    groups.sort(key=lambda g: (-g["count"], g["key"]))
    return [{"question": g["example"], "count": g["count"]} for g in groups[:limit]]


def sources(db: Session, bot_id: str, w: Window, limit: int = TOP_N) -> list[dict]:
    chats = _chat_ids(db, bot_id, w.start, w.end)
    if not chats:
        return []
    origin_of: dict[str, str] = {}
    rows = db.execute(
        select(AccessLog.session_id, AccessLog.detail)
        .where(
            AccessLog.bot_id == bot_id,
            AccessLog.event == "WIDGET_OPENED",
            AccessLog.created_at >= w.start - timedelta(days=1),
            AccessLog.created_at < w.end,
        )
        .order_by(AccessLog.created_at)
    )
    for sid, detail in rows:
        if sid in chats and detail and sid not in origin_of:
            origin_of[sid] = detail
    counts: dict[str, int] = defaultdict(int)
    for sid in chats:
        counts[origin_of.get(sid, DIRECT)] += 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [{"origin": o, "chats": n} for o, n in top]


def status(db: Session, bot: Bot, today: date) -> dict:
    cfg = llm_configs.get(db, bot.id)
    from mebot.telegram import outbox
    from mebot.telegram import repo as tg_repo

    tg = tg_repo.get(db, bot.id)
    linked = bool(tg and tg.bot_token_encrypted and tg.chat_id)
    dead = outbox.stats(db, bot.id)["dead"] if tg else 0
    ws = db.scalar(select(WidgetSettings).where(WidgetSettings.bot_id == bot.id))
    limits = limits_repo.get_or_create(db, bot.id)
    day = db.scalar(
        select(UsageCounter).where(
            UsageCounter.bot_id == bot.id,
            UsageCounter.scope == "bot_day",
            UsageCounter.key == "*",
            UsageCounter.window_start == today.isoformat(),
        )
    )
    return {
        "llm": {
            "configured": cfg is not None,
            "ok": bool(cfg and cfg.last_test_ok),
            "last_tested_at": _iso(cfg.last_tested_at) if cfg else None,
        },
        "telegram": {"linked": linked, "dead": dead},
        "widget": {
            "enabled": bool(ws and ws.enabled),
            "origins": len(widget_repo.origins(ws)) if ws else 0,
            "any_origin": bool(ws and ws.allow_any_origin),
        },
        "paused": bool(limits.paused),
        "today": {
            "messages": day.messages if day else 0,
            "cap": limits.daily_message_cap,
            "tokens": day.tokens if day else 0,
            "token_cap": limits.daily_token_cap,
        },
    }


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def overview(db: Session, bot: Bot, range_key: str, now: datetime | None = None) -> dict:
    now = now or utcnow()
    zone = tzmod.safe_zone(bot.timezone)
    w = window(zone, range_key, now)
    return {
        "range": {
            "key": range_key,
            "from": w.days[0].isoformat(),
            "to": w.days[-1].isoformat(),
            "timezone": zone.key,
        },
        "kpis": kpis(db, bot.id, w),
        "series": series(db, bot.id, w),
        "top_questions": top_questions(db, bot.id, w),
        "sources": sources(db, bot.id, w),
        "status": status(db, bot, now.astimezone(UTC).date()),
    }


def cached_overview(db: Session, bot: Bot, range_key: str) -> dict:
    hit = cache.get(bot.id, range_key, bot.timezone)
    if hit is not None:
        return hit
    value = overview(db, bot, range_key)
    cache.put(bot.id, range_key, bot.timezone, value)
    return value
