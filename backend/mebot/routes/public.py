"""Unauthenticated config the recruiter UI (and later the widget) reads on load."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from mebot import persona, turnstile
from mebot.db import get_db
from mebot.deps import get_current_bot
from mebot.models import Bot
from mebot.profile.data import load_profile
from mebot.repos import limits as limits_repo
from mebot.repos import profile_items

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
        # Shown to recruiters (consent line, "{name} replied:"); identity name, else bot name.
        "owner_name": _owner_name(db, bot),
        # The recruiter chat's first bubble; rendered server-side, not an LLM call.
        "assistant_greeting": persona.render_greeting(load_profile(db, bot.id).identity, bot.name),
    }


def _owner_name(db: Session, bot: Bot) -> str:
    ident = profile_items.get_identity(db, bot.id)
    return (ident.full_name.strip() if ident else "") or bot.name
