from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from mebot.db import get_db
from mebot.deps import get_current_bot
from mebot.models import Bot
from mebot.repos import logs

router = APIRouter(prefix="/api")


@router.get("/log")
def read_log(
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    return logs.recent(db, bot.id, limit)
