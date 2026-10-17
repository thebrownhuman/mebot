"""Owner-only limits (incl. pause) and usage. Setup, session and CSRF on writes."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from mebot.db import get_db
from mebot.deps import csrf_on_mutation, get_current_admin, get_current_bot, require_setup_done
from mebot.errors import ApiError
from mebot.hosted import caps
from mebot.limits import counters
from mebot.models import AccessLog, Bot, BotLimits
from mebot.repos import limits as limits_repo
from mebot.repos import logs
from mebot.telegram import events

router = APIRouter(
    prefix="/api/admin",
    dependencies=[
        Depends(require_setup_done),
        Depends(get_current_admin),
        Depends(csrf_on_mutation),
    ],
)

FIELDS = (
    "per_ip_per_minute",
    "per_ip_per_day",
    "per_session_messages",
    "sessions_per_ip_per_hour",
    "daily_message_cap",
    "daily_token_cap",
    "max_message_chars",
    "history_turns",
    "paused",
    "paused_message",
    "turnstile_enabled",
)


class LimitsIn(BaseModel):
    """Partial update: only the fields sent are changed."""

    model_config = ConfigDict(extra="forbid")

    per_ip_per_minute: int = Field(default=None, ge=1, le=120)
    per_ip_per_day: int = Field(default=None, ge=1, le=10_000)
    per_session_messages: int = Field(default=None, ge=1, le=1_000)
    sessions_per_ip_per_hour: int = Field(default=None, ge=1, le=1_000)
    daily_message_cap: int = Field(default=None, ge=1, le=100_000)
    daily_token_cap: int | None = Field(default=None, ge=1_000, le=100_000_000)
    max_message_chars: int = Field(default=None, ge=100, le=4_000)
    history_turns: int = Field(default=None, ge=2, le=50)
    paused: bool = None
    paused_message: str | None = Field(default=None, max_length=500)
    turnstile_enabled: bool = None


def _available(request: Request) -> bool:
    s = request.app.state.settings
    return bool(s.turnstile_site_key and s.turnstile_secret_key)


def _out(row: BotLimits, request: Request) -> dict:
    settings = request.app.state.settings
    view = caps.clamp(row, settings)
    body = {f: getattr(view, f) for f in FIELDS}
    body["turnstile_available"] = _available(request)
    if settings.hosted:
        body["caps"] = caps.caps(settings)
    return body


@router.get("/limits")
def get_limits(
    request: Request, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)
):
    return _out(limits_repo.get_or_create(db, bot.id), request)


@router.put("/limits")
def put_limits(
    req: LimitsIn,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    values = req.model_dump(exclude_unset=True)
    caps.check(values, request.app.state.settings)
    if values.get("paused_message") is not None:
        values["paused_message"] = values["paused_message"].strip() or None
    if values.get("turnstile_enabled") and not _available(request):
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "Invalid request",
            [
                {
                    "field": "turnstile_enabled",
                    "message": "set TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY first",
                }
            ],
        )
    row = limits_repo.get_or_create(db, bot.id)
    was_paused = row.paused
    limits_repo.update(db, row, values)
    if row.paused != was_paused:
        events.paused(db, bot.id, row.paused)
    logs.add(db, bot.id, None, "limits_updated", detail=",".join(sorted(values)))
    db.commit()
    return _out(row, request)


def _short(ip_hash: str) -> str:
    return ip_hash[:4] + "…"


@router.get("/usage")
def usage(
    request: Request,
    days: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    today = request.app.state.chat_limiter.today()
    dates = [today - timedelta(days=i) for i in range(days)]
    since = dates[-1]
    per_day = {
        d.isoformat(): {
            "date": d.isoformat(),
            "messages": 0,
            "tokens": 0,
            "tokens_estimated": False,
            "rate_limited": 0,
            "leak_blocked": 0,
        }
        for d in dates
    }
    visitors: dict[str, int] = defaultdict(int)
    for row in counters.daily(db, bot.id, since):
        if row.scope == "bot_day" and row.window_start in per_day:
            day = per_day[row.window_start]
            day["messages"] += row.messages
            day["tokens"] += row.tokens
            day["tokens_estimated"] = day["tokens_estimated"] or row.estimated_tokens > 0
        elif row.scope == "ip_day":
            visitors[row.key] += row.messages
    # RATE_LIMITED is logged at most once per visitor and scope per minute, so this
    # counts throttled visitor-minutes rather than every refused request.
    events = db.execute(
        select(AccessLog.event, AccessLog.created_at).where(
            AccessLog.bot_id == bot.id,
            AccessLog.event.in_(("RATE_LIMITED", "LEAK_BLOCKED")),
            AccessLog.created_at >= datetime.combine(since, datetime.min.time(), UTC),
        )
    )
    for event, created_at in events:
        key = created_at.astimezone(UTC).date().isoformat()
        if key in per_day:
            per_day[key]["rate_limited" if event == "RATE_LIMITED" else "leak_blocked"] += 1
    top = sorted(((m, k) for k, m in visitors.items() if m > 0), reverse=True)[:5]
    return {
        "days": list(per_day.values()),
        "top_visitors": [{"ip_hash": _short(k), "messages": m} for m, k in top],
    }
