from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mebot.db import get_db
from mebot.deps import client_ip, get_current_bot
from mebot.limits.service import LimitExceeded
from mebot.models import Bot
from mebot.repos import limits as limits_repo
from mebot.repos import logs, sessions

router = APIRouter(prefix="/api")


class StartReq(BaseModel):
    recruiter_name: str | None = Field(default=None, max_length=120)


@router.post("/session")
def start_session(
    req: StartReq,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    ip = client_ip(request)
    limits = limits_repo.get_or_create(db, bot.id)
    limiter = request.app.state.chat_limiter
    wait = limiter.session_start_wait(limits, ip)
    if wait is not None:
        if limiter.should_log("session_start", limiter.ip_key(ip)):
            logs.add(db, bot.id, None, "RATE_LIMITED", detail="session_start")
            db.commit()
        raise LimitExceeded("session_start", wait).api_error()
    sid = sessions.create(db, bot.id, req.recruiter_name)
    logs.add(db, bot.id, sid, "session_start", detail=req.recruiter_name, ip=ip)
    db.commit()
    return {"session_id": sid}
