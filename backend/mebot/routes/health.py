from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from mebot import __version__
from mebot.db import get_db
from mebot.deps import get_current_bot
from mebot.llm import service as llm
from mebot.models import Bot
from mebot.repos import admins

router = APIRouter(prefix="/api")


@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)):
    """Whether chat can work, from stored state only (no provider call, no cost).

    Hosted mode without a tenant (/b/{ref} or subdomain) answers for the platform: the
    process is up, and nothing about any tenant (container health checks hit this)."""
    if request.app.state.settings.hosted and not request.scope.get("state", {}).get(
        "tenant_bot_id"
    ):
        return {"ready": True, "model": None, "version": __version__}
    bot: Bot = get_current_bot(request, db)
    return {**_status(request, db, bot), "version": __version__}


def _status(request: Request, db: Session, bot: Bot) -> dict:
    if not request.app.state.settings.hosted and not admins.exists(db):
        return {"ready": False, "model": None, "message": "setup required"}
    status, row, _ = llm.load(db, bot.id, request.app.state.secret_key)
    if status != "ok":
        return {"ready": False, "model": None, "message": "assistant not configured"}
    if row.last_test_ok is False:
        return {"ready": False, "model": row.model, "message": "assistant unavailable"}
    return {"ready": True, "model": row.model}
