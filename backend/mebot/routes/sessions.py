from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mebot import turnstile
from mebot.db import get_db
from mebot.deps import client_ip, get_current_bot
from mebot.errors import ApiError
from mebot.limits import counters
from mebot.limits.service import LimitExceeded
from mebot.models import Bot
from mebot.repos import limits as limits_repo
from mebot.repos import logs, sessions
from mebot.telegram import events

router = APIRouter(prefix="/api")

TURNSTILE_FAILED = "We couldn't verify you're human. Please refresh the page and try again."
TURNSTILE_DOWN = "Verification is unavailable right now. Please try again in a few minutes."


class StartReq(BaseModel):
    recruiter_name: str | None = Field(default=None, max_length=120)
    turnstile_token: str | None = Field(default=None, max_length=4096)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@router.get("/session/{sid}/updates")
def session_updates(
    sid: str,
    request: Request,
    after: str | None = Query(None, max_length=40),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    """Owner replies (from Telegram) the recruiter's open chat hasn't shown yet."""
    ip = client_ip(request)
    wait = request.app.state.updates_limiter.hit(request.app.state.chat_limiter.ip_key(ip))
    if wait is not None:
        raise ApiError(
            429,
            "RATE_LIMITED",
            "Too many requests. Please wait a moment.",
            headers={"Retry-After": str(wait)},
        )
    since = None
    if after:
        try:
            since = datetime.fromisoformat(after.replace("Z", "+00:00"))
        except ValueError:
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                "Invalid request",
                [{"field": "after", "message": "ISO time"}],
            ) from None
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
    if sessions.get(db, bot.id, sid) is None:
        raise ApiError(404, "NOT_FOUND", "Unknown session")
    return {
        "messages": [
            {
                "role": m.role,
                "from_owner": True,
                "content": m.content,
                "created_at": _iso(m.created_at),
            }
            for m in sessions.owner_messages(db, bot.id, sid, since)
        ],
        # Lets the chat suggest "Leave my contact" after a reply the bot couldn't give.
        "unanswered": sessions.last_reply_unanswered(db, bot.id, sid),
    }


@router.post("/session")
async def start_session(
    req: StartReq,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    ip = client_ip(request)
    settings = request.app.state.settings
    limits = limits_repo.get_or_create(db, bot.id)
    limiter = request.app.state.chat_limiter
    wait = limiter.session_start_wait(limits, ip)
    if wait is not None:
        if limiter.should_log("session_start", limiter.ip_key(ip)):
            logs.add(db, bot.id, None, "RATE_LIMITED", detail="session_start")
            db.commit()
        raise LimitExceeded("session_start", wait).api_error()
    if turnstile.active(settings, limits):
        if not req.turnstile_token:
            raise ApiError(403, "TURNSTILE_FAILED", TURNSTILE_FAILED)
        try:
            ok = await turnstile.verify(settings.turnstile_secret_key, req.turnstile_token, ip)
        except turnstile.TurnstileUnavailable:  # fail closed; the owner can disable it
            raise ApiError(503, "TURNSTILE_UNAVAILABLE", TURNSTILE_DOWN) from None
        if not ok:
            raise ApiError(403, "TURNSTILE_FAILED", TURNSTILE_FAILED)
    sid = sessions.create(db, bot.id, req.recruiter_name)
    logs.add(
        db,
        bot.id,
        sid,
        "session_start",
        detail=req.recruiter_name,
        ip_hash=counters.stored_ip_hash(request.app.state.secret_key, ip),
    )
    events.new_session(db, bot.id, sid, req.recruiter_name)
    db.commit()
    return {"session_id": sid}
