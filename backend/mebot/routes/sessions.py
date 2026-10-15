from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from mebot.db import get_db
from mebot.deps import client_ip, get_current_bot
from mebot.models import Bot
from mebot.repos import logs, sessions

router = APIRouter(prefix="/api")


class StartReq(BaseModel):
    recruiter_name: str | None = None


@router.post("/session")
def start_session(
    req: StartReq,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    sid = sessions.create(db, bot.id, req.recruiter_name)
    logs.add(db, bot.id, sid, "session_start", detail=req.recruiter_name, ip=client_ip(request))
    db.commit()
    return {"session_id": sid}
