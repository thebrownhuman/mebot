"""Owner-only endpoints. Every route here needs setup done, a session, and CSRF on writes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from mebot.db import get_db
from mebot.deps import csrf_on_mutation, get_current_admin, get_current_bot, require_setup_done
from mebot.models import Bot
from mebot.repos import logs, sessions

router = APIRouter(
    prefix="/api/admin",
    dependencies=[
        Depends(require_setup_done),
        Depends(get_current_admin),
        Depends(csrf_on_mutation),
    ],
)


@router.get("/sessions")
def list_sessions(db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    return sessions.list_with_turns(db, bot.id)


@router.get("/sessions/{sid}/messages")
def session_messages(sid: str, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    if sessions.get(db, bot.id, sid) is None:
        raise HTTPException(404, "Unknown session")
    return [
        {"role": m.role, "content": m.content, "ts": m.created_at.timestamp()}
        for m in sessions.messages(db, bot.id, sid)
    ]


@router.get("/unanswered")
def read_unanswered(
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    return {"items": logs.unanswered(db, bot.id, limit)}


@router.get("/log")
def read_log(
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    return logs.recent(db, bot.id, limit)
