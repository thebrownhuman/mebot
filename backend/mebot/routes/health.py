from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from mebot.db import get_db
from mebot.deps import get_current_bot
from mebot.llm import service as llm
from mebot.models import Bot
from mebot.repos import admins

router = APIRouter(prefix="/api")


@router.get("/health")
def health(request: Request, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    """Whether chat can work, from stored state only (no provider call, no cost)."""
    if not admins.exists(db):
        return {"ready": False, "model": None, "message": "setup required"}
    status, row, _ = llm.load(db, bot.id, request.app.state.secret_key)
    if status != "ok":
        return {"ready": False, "model": None, "message": "assistant not configured"}
    if row.last_test_ok is False:
        return {"ready": False, "model": row.model, "message": "assistant unavailable"}
    return {"ready": True, "model": row.model}
