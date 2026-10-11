from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from mebot.db import get_db
from mebot.deps import get_current_bot
from mebot.models import Bot
from mebot.repos import logs, profiles

router = APIRouter(prefix="/api")


class ProfileReq(BaseModel):
    content: str


@router.get("/profile")
def read_profile(db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    return {"content": profiles.get_content(db, bot.id)}


@router.put("/profile")
def write_profile(
    req: ProfileReq, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)
):
    profiles.save(db, bot.id, req.content)
    logs.add(db, bot.id, None, "profile_updated")
    db.commit()
    return {"ok": True}
