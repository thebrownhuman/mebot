"""Unauthenticated config the recruiter UI (and later the widget) reads on load."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from mebot import turnstile
from mebot.db import get_db
from mebot.deps import get_current_bot
from mebot.models import Bot
from mebot.repos import limits as limits_repo

router = APIRouter(prefix="/api/public")


@router.get("/config")
def public_config(
    request: Request, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)
):
    settings = request.app.state.settings
    limits = limits_repo.get_or_create(db, bot.id)
    return {
        "turnstile_site_key": settings.turnstile_site_key
        if turnstile.active(settings, limits)
        else None,
        "max_message_chars": limits.max_message_chars,
        "paused": limits.paused,
    }
