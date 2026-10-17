"""Conversation queries for the owner: filtered list, detail, export rows.

All filters are conditions on ``sessions`` (``EXISTS`` subqueries on messages / contacts /
access_log), so the list, the count and the export share one definition of "matches".
"""

import base64
import binascii
import csv
import io
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, and_, cast, func, or_, select
from sqlalchemy.orm import Session

from mebot import tz
from mebot.analytics import service as analytics
from mebot.errors import ApiError
from mebot.models import AccessLog, Bot, ChatSession, Contact, Message, utcnow

HAS = ("unanswered", "contact", "owner_reply", "leak_blocked")
DIRECT = "direct"
MAX_EXPORT_MESSAGES = 50_000
MIN_QUERY = 2
PREVIEW_CHARS = 140
# Log events shown as badges on a conversation.
BADGE_EVENTS = (
    "UNANSWERED",
    "PERSONAL_DECLINED",
    "LEAK_BLOCKED",
    "CHANNEL_REDACTED",
    "OWNER_REPLIED",
    "CONTACT_LEFT",
    "RATE_LIMITED",
    "WIDGET_OPENED",
)
_FLAG_EVENTS = {"LEAK_BLOCKED": "leak_blocked", "CHANNEL_REDACTED": "redacted"}


def _bad(field_name: str, message: str) -> ApiError:
    return ApiError(
        422, "VALIDATION_ERROR", "Invalid request", [{"field": field_name, "message": message}]
    )


@dataclass
class Filters:
    start: datetime | None = None
    end: datetime | None = None
    q: str | None = None
    has: tuple[str, ...] = ()
    origin: str | None = None
    zone: ZoneInfo = field(default_factory=lambda: ZoneInfo("UTC"))


def _day(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _bad(name, "use YYYY-MM-DD") from None


def parse_filters(
    bot: Bot,
    *,
    range: str | None,
    date_from: str | None,
    date_to: str | None,
    q: str | None,
    has: str | None,
    origin: str | None,
    now: datetime | None = None,
) -> Filters:
    zone = tz.safe_zone(bot.timezone)
    f = Filters(zone=zone, origin=(origin or "").strip() or None)
    if date_from or date_to:
        lo = _day(date_from, "from") if date_from else None
        hi = _day(date_to, "to") if date_to else None
        if lo and hi and lo > hi:
            raise _bad("from", "must not be after 'to'")
        if lo:
            f.start = datetime.combine(lo, time.min, zone).astimezone(UTC)
        if hi:
            f.end = datetime.combine(hi + timedelta(days=1), time.min, zone).astimezone(UTC)
    elif range:
        if range not in analytics.RANGES:
            raise _bad("range", "use 7d, 30d or 90d")
        w = analytics.window(zone, range, now or utcnow())
        f.start, f.end = w.start, w.end
    if q is not None:
        q = " ".join(q.split())
        if len(q) < MIN_QUERY:
            raise _bad("q", f"type at least {MIN_QUERY} characters")
        f.q = q
    if has:
        items = tuple(dict.fromkeys(p.strip() for p in has.split(",") if p.strip()))
        unknown = [i for i in items if i not in HAS]
        if unknown:
            raise _bad("has", f"unknown: {', '.join(unknown)} (use {', '.join(HAS)})")
        f.has = items
    return f


def like_pattern(q: str) -> str:
    """Case-insensitive substring pattern with %, _ and the escape char taken literally."""
    escaped = q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _ev(bot_id: str, event: str):
    # No bot_id here: the outer sessions.bot_id filter scopes it, and leaving it out lets
    # the planner look rows up by session_id instead of scanning the whole bot.
    return (
        select(AccessLog.id)
        .where(
            AccessLog.session_id == ChatSession.id,
            AccessLog.event == event,
        )
        .exists()
    )


def conditions(bot_id: str, f: Filters) -> list:
    c = [ChatSession.bot_id == bot_id]
    if f.start is not None:
        c.append(ChatSession.started_at >= f.start)
    if f.end is not None:
        c.append(ChatSession.started_at < f.end)
    if f.q:
        c.append(
            select(Message.id)
            .where(
                Message.session_id == ChatSession.id,
                func.lower(Message.content).like(like_pattern(f.q), escape="\\"),
            )
            .exists()
        )
    for h in f.has:
        if h == "unanswered":
            c.append(
                select(Message.id)
                .where(
                        Message.session_id == ChatSession.id,
                    Message.unanswered.is_(True),
                )
                .exists()
            )
        elif h == "owner_reply":
            c.append(
                select(Message.id)
                .where(
                        Message.session_id == ChatSession.id,
                    Message.from_owner.is_(True),
                )
                .exists()
            )
        elif h == "contact":
            c.append(
                select(Contact.id)
                .where(
                    Contact.session_id == ChatSession.id,
                    Contact.deleted_at.is_(None),
                )
                .exists()
            )
        elif h == "leak_blocked":
            c.append(_ev(bot_id, "LEAK_BLOCKED"))
    if f.origin:
        opened = (
            select(AccessLog.id)
            .where(
                    AccessLog.session_id == ChatSession.id,
                AccessLog.event == "WIDGET_OPENED",
            )
        )
        if f.origin == DIRECT:
            c.append(~opened.exists())
        else:
            c.append(opened.where(AccessLog.detail == f.origin).exists())
    return c


# --- cursor -------------------------------------------------------------------------------


def encode_cursor(started_at: datetime, sid: str) -> str:
    raw = f"{started_at.astimezone(UTC).isoformat()}|{sid}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        ts, sid = raw.split("|", 1)
        return datetime.fromisoformat(ts), sid
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise _bad("cursor", "invalid cursor") from None


# --- list ---------------------------------------------------------------------------------


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def list_page(
    db: Session, bot_id: str, f: Filters, cursor: str | None, limit: int
) -> tuple[list[dict], str | None]:
    where = conditions(bot_id, f)
    if cursor:
        ts, sid = decode_cursor(cursor)
        where.append(
            or_(
                ChatSession.started_at < ts,
                and_(ChatSession.started_at == ts, ChatSession.id < sid),
            )
        )
    rows = db.execute(
        select(ChatSession.id, ChatSession.recruiter_name, ChatSession.started_at)
        .where(*where)
        .order_by(ChatSession.started_at.desc(), ChatSession.id.desc())
        .limit(limit + 1)
    ).all()
    more = len(rows) > limit
    rows = rows[:limit]
    items = _decorate(db, bot_id, rows)
    nxt = encode_cursor(rows[-1][2], rows[-1][0]) if more and rows else None
    return items, nxt


def _decorate(db: Session, bot_id: str, rows) -> list[dict]:
    ids = [r[0] for r in rows]
    if not ids:
        return []
    stats = {
        sid: (n, last, bool(un), bool(owner))
        for sid, n, last, un, owner in db.execute(
            select(
                Message.session_id,
                func.count(Message.id),
                func.max(Message.created_at),
                func.max(cast(Message.unanswered, Integer)),
                func.max(cast(Message.from_owner, Integer)),
            )
            .where(Message.bot_id == bot_id, Message.session_id.in_(ids))
            .group_by(Message.session_id)
        )
    }
    contacts = set(
        db.scalars(
            select(Contact.session_id).where(
                Contact.bot_id == bot_id,
                Contact.session_id.in_(ids),
                Contact.deleted_at.is_(None),
            )
        )
    )
    events: dict[str, set[str]] = {}
    origin: dict[str, str] = {}
    for sid, ev, detail in db.execute(
        select(AccessLog.session_id, AccessLog.event, AccessLog.detail)
        .where(
            AccessLog.bot_id == bot_id,
            AccessLog.session_id.in_(ids),
            AccessLog.event.in_(("LEAK_BLOCKED", "CHANNEL_REDACTED", "WIDGET_OPENED")),
        )
        .order_by(AccessLog.created_at)
    ):
        if ev == "WIDGET_OPENED":
            if detail:
                origin.setdefault(sid, detail)
        else:
            events.setdefault(sid, set()).add(_FLAG_EVENTS[ev])
    preview = _previews(db, bot_id, ids)
    out = []
    for sid, name, started in rows:
        n, last, un, owner = stats.get(sid, (0, None, False, False))
        flags = set(events.get(sid, ()))
        if un:
            flags.add("unanswered")
        if owner:
            flags.add("owner_reply")
        if sid in contacts:
            flags.add("contact")
        out.append(
            {
                "id": sid,
                "recruiter_name": name,
                "started_at": _iso(started),
                "last_message_at": _iso(last) or _iso(started),
                "messages": n,
                "origin": origin.get(sid, DIRECT),
                "flags": sorted(flags),
                "preview": preview.get(sid, ""),
            }
        )
    return out


def _previews(db: Session, bot_id: str, ids: list[str]) -> dict[str, str]:
    first = (
        select(Message.session_id, func.min(Message.created_at).label("t"))
        .where(Message.bot_id == bot_id, Message.session_id.in_(ids), Message.role == "user")
        .group_by(Message.session_id)
        .subquery()
    )
    rows = db.execute(
        select(Message.session_id, Message.content).join(
            first, and_(Message.session_id == first.c.session_id, Message.created_at == first.c.t)
        )
    )
    out: dict[str, str] = {}
    for sid, content in rows:
        text = " ".join((content or "").split())
        out.setdefault(sid, text[:PREVIEW_CHARS] + ("…" if len(text) > PREVIEW_CHARS else ""))
    return out


# --- detail -------------------------------------------------------------------------------


def detail(db: Session, bot_id: str, sid: str) -> dict | None:
    s = db.scalar(select(ChatSession).where(ChatSession.id == sid, ChatSession.bot_id == bot_id))
    if s is None:
        return None
    msgs = db.scalars(
        select(Message)
        .where(Message.bot_id == bot_id, Message.session_id == sid)
        .order_by(Message.created_at, Message.id)
    ).all()
    logs = db.scalars(
        select(AccessLog)
        .where(
            AccessLog.bot_id == bot_id,
            AccessLog.session_id == sid,
            AccessLog.event.in_(BADGE_EVENTS),
        )
        .order_by(AccessLog.created_at, AccessLog.id)
    ).all()
    contact = db.scalar(
        select(Contact)
        .where(Contact.bot_id == bot_id, Contact.session_id == sid, Contact.deleted_at.is_(None))
        .order_by(Contact.created_at)
    )
    origin = next((e.detail for e in logs if e.event == "WIDGET_OPENED" and e.detail), DIRECT)
    return {
        "id": s.id,
        "recruiter_name": s.recruiter_name,
        "started_at": _iso(s.started_at),
        "origin": origin,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "unanswered": m.unanswered,
                "from_owner": m.from_owner,
            }
            for m in msgs
        ],
        "events": [
            {
                "event": e.event,
                "created_at": _iso(e.created_at),
                **({"detail": e.detail} if e.event == "WIDGET_OPENED" else {}),
            }
            for e in logs
        ],
        "contact": None
        if contact is None
        else {
            "id": contact.id,
            "name": contact.name,
            "email": contact.email,
            "company": contact.company,
            "role": contact.role,
            "note": contact.note,
            "created_at": _iso(contact.created_at),
        },
    }


# --- export -------------------------------------------------------------------------------

CSV_COLUMNS = (
    "session_id",
    "started_at",
    "recruiter_name",
    "origin",
    "role",
    "created_at",
    "content",
    "unanswered",
    "from_owner",
)
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value) -> str:
    """CSV cells opening a formula in Excel/Sheets get a leading apostrophe."""
    s = "" if value is None else str(value)
    return "'" + s if s.startswith(_FORMULA_START) else s


def export_count(db: Session, bot_id: str, f: Filters) -> int:
    sub = select(ChatSession.id).where(*conditions(bot_id, f)).scalar_subquery()
    return (
        db.scalar(
            select(func.count()).select_from(Message).where(Message.bot_id == bot_id, Message.session_id.in_(sub))
        )
        or 0
    )


def export_rows(db: Session, bot_id: str, f: Filters) -> Iterator[dict]:
    sess = {
        sid: (name, started)
        for sid, name, started in db.execute(
            select(ChatSession.id, ChatSession.recruiter_name, ChatSession.started_at).where(
                *conditions(bot_id, f)
            )
        )
    }
    origin: dict[str, str] = {}
    for sid, detail_ in db.execute(
        select(AccessLog.session_id, AccessLog.detail)
        .where(AccessLog.bot_id == bot_id, AccessLog.event == "WIDGET_OPENED")
        .order_by(AccessLog.created_at)
    ):
        if sid in sess and detail_:
            origin.setdefault(sid, detail_)
    ordered = sorted(sess, key=lambda i: (sess[i][1], i))
    for i in range(0, len(ordered), 200):
        part = ordered[i : i + 200]
        by_sid: dict[str, list[Message]] = {sid: [] for sid in part}
        for m in db.scalars(
            select(Message)
            .where(Message.bot_id == bot_id, Message.session_id.in_(part))
            .order_by(Message.created_at, Message.id)
        ):
            by_sid[m.session_id].append(m)
        for sid in part:
            name, started = sess[sid]
            for m in by_sid[sid]:
                yield {
                    "session_id": sid,
                    "started_at": _iso(started),
                    "recruiter_name": name,
                    "origin": origin.get(sid, DIRECT),
                    "role": m.role,
                    "created_at": m.created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                    "content": m.content,
                    "unanswered": m.unanswered,
                    "from_owner": m.from_owner,
                }


def csv_stream(rows: Iterator[dict]) -> Iterator[str]:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLUMNS)
    yield "﻿" + _drain(buf)  # BOM so Excel reads UTF-8
    for row in rows:
        w.writerow(
            [
                safe_cell(row[c]) if c not in ("unanswered", "from_owner") else str(row[c]).lower()
                for c in CSV_COLUMNS
            ]
        )
        yield _drain(buf)


def json_stream(rows: Iterator[dict]) -> Iterator[str]:
    yield "["
    first = True
    for row in rows:
        yield ("" if first else ",") + json.dumps(row, ensure_ascii=False)
        first = False
    yield "]"


def _drain(buf: io.StringIO) -> str:
    out = buf.getvalue()
    buf.seek(0)
    buf.truncate()
    return out
