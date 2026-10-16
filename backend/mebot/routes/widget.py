"""Widget surfaces: the embed page, the loader script, and the settings it reads."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from mebot import persona, turnstile
from mebot.db import get_db
from mebot.errors import ApiError
from mebot.models import Bot, WidgetSettings
from mebot.profile.data import load_profile
from mebot.repos import admins, bots
from mebot.repos import limits as limits_repo
from mebot.repos import widget as widget_repo
from mebot.widget.frames import EMBED_HTML, UNAVAILABLE_HTML, embed_csp

router = APIRouter()

LOADER_CACHE = "public, max-age=86400"


def resolve(db: Session, slug: str) -> tuple[Bot, WidgetSettings] | None:
    """The bot behind an embed slug, while setup is done and its widget is enabled.

    Single mode serves one bot, so any other slug is unknown."""
    if not admins.exists(db):
        return None
    bot = bots.get_primary(db)
    if bot.slug != slug:
        return None
    row = widget_repo.get_or_create(db, bot.id)
    return (bot, row) if row.enabled else None


@router.get("/embed/{slug}", response_class=HTMLResponse)
def embed_page(slug: str, db: Session = Depends(get_db)):
    found = resolve(db, slug)
    if found is None:
        return HTMLResponse(
            UNAVAILABLE_HTML,
            status_code=404,
            headers={"Content-Security-Policy": embed_csp(None)},
        )
    return HTMLResponse(
        EMBED_HTML,
        headers={"Content-Security-Policy": embed_csp(found[1]), "Cache-Control": "no-cache"},
    )


@router.get("/widget/v1.js")
def loader(request: Request):
    path = request.app.state.settings.frontend_dist / "widget" / "v1.js"
    if not path.is_file():
        raise ApiError(404, "NOT_BUILT", "Widget loader not built (run npm run build)")
    return FileResponse(path, media_type="text/javascript", headers={"Cache-Control": LOADER_CACHE})


@router.get("/widget.js")
def loader_alias():
    return RedirectResponse("/widget/v1.js", status_code=302)


@router.get("/api/public/widget/{slug}")
def public_widget(slug: str, request: Request, db: Session = Depends(get_db)):
    """What the embed needs to render. Never the allowed-sites list."""
    found = resolve(db, slug)
    if found is None:
        raise ApiError(404, "WIDGET_UNAVAILABLE", "This chat is unavailable")
    bot, row = found
    limits = limits_repo.get_or_create(db, bot.id)
    identity = load_profile(db, bot.id).identity
    first = persona.display_name(identity, bot.name)
    settings = request.app.state.settings
    return {
        "title": row.title or f"{first}'s assistant",
        "primary_color": row.primary_color,
        "theme": row.theme,
        "position": row.position,
        "avatar_url": row.avatar_url,
        "launcher_label": row.launcher_label,
        "greeting": persona.render_greeting(identity, bot.name),
        "suggested_questions": widget_repo.questions(row),
        "show_orb": row.show_orb,
        "auto_open_seconds": row.auto_open_seconds,
        "max_message_chars": limits.max_message_chars,
        "turnstile_site_key": settings.turnstile_site_key
        if turnstile.active(settings, limits)
        else None,
        "owner_first_name": first,
        "paused": limits.paused,
    }
