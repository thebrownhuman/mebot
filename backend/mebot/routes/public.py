"""Unauthenticated config the recruiter UI (and later the widget) reads on load."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from mebot import channels, persona, turnstile
from mebot.db import get_db
from mebot.deps import client_ip, get_current_bot
from mebot.errors import ApiError
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


@router.get("/contact-channels")
def contact_channels(
    request: Request, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)
):
    """The channels the owner shares with recruiters. Nothing else is ever returned."""
    ip = client_ip(request)
    wait = request.app.state.channels_limiter.hit(request.app.state.chat_limiter.ip_key(ip))
    if wait is not None:
        raise ApiError(
            429,
            "RATE_LIMITED",
            "Too many requests. Please wait a moment.",
            headers={"Retry-After": str(wait)},
        )
    items = channels.from_items(load_profile(db, bot.id).items("links"))
    return {
        "items": [
            {"kind": c.kind, "label": c.label, "display": c.display, "href": c.href}
            for c in items
            if c.share
        ]
    }


def _owner_name(db: Session, bot: Bot) -> str:
    ident = profile_items.get_identity(db, bot.id)
    return (ident.full_name.strip() if ident else "") or bot.name
