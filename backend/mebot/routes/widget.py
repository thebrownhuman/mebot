"""Widget surfaces: the embed page, the loader script, and the settings it reads."""

import re
from html import escape

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from mebot import persona, turnstile
from mebot.db import get_db
from mebot.deps import client_ip, get_current_admin
from mebot.errors import ApiError
from mebot.models import AccessLog, Bot, WidgetSettings
from mebot.profile.data import load_profile
from mebot.repos import admins, bots, logs
from mebot.repos import limits as limits_repo
from mebot.repos import widget as widget_repo
from mebot.widget.frames import EMBED_HTML, UNAVAILABLE_HTML, embed_csp
from mebot.widget.origins import OriginError, matches, normalise

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


@router.get("/api/public/widget/{slug}/launcher")
def launcher_settings(slug: str, request: Request, db: Session = Depends(get_db)):
    """The few fields the loader needs to draw the launcher on the host page.

    The only cross-origin read in the widget: CORS is granted to allowed sites only (no
    credentials), so a site that may not frame the chat gets no launcher either."""
    found = resolve(db, slug)
    if found is None:
        raise ApiError(404, "WIDGET_UNAVAILABLE", "This chat is unavailable")
    bot, row = found
    origin = request.headers.get("origin")
    headers = {"Vary": "Origin", "Cache-Control": "no-cache"}
    if origin and origin != base_origin(request):
        if row.allow_any_origin:
            headers["Access-Control-Allow-Origin"] = "*"
        elif matches(origin, widget_repo.origins(row)):
            headers["Access-Control-Allow-Origin"] = origin
        else:
            raise ApiError(403, "WIDGET_NOT_ALLOWED", "This site may not embed the chat")
    first = persona.display_name(load_profile(db, bot.id).identity, bot.name)
    body = {
        "title": row.title or f"{first}'s assistant",
        "primary_color": row.primary_color,
        "position": row.position,
        "theme": row.theme,
        "launcher_label": row.launcher_label,
        "auto_open_seconds": row.auto_open_seconds,
    }
    return JSONResponse(body, headers=headers)


def base_origin(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}"


class OpenedIn(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)
    origin: str = Field(max_length=300)


@router.post("/api/public/widget/{slug}/opened", status_code=204)
def widget_opened(slug: str, req: OpenedIn, request: Request, db: Session = Depends(get_db)):
    """WIDGET_OPENED analytics: the host site's origin, once per chat session.

    The origin comes from the loader's host-info message, so it is only stored when it
    is one the owner allowed. Always 204: callers learn nothing about the list."""
    found = resolve(db, slug)
    if found is None:
        raise ApiError(404, "WIDGET_UNAVAILABLE", "This chat is unavailable")
    bot, row = found
    limiter = request.app.state.channels_limiter
    if limiter.hit(request.app.state.chat_limiter.ip_key(client_ip(request))) is not None:
        return Response(status_code=204)
    if row.allow_any_origin:
        try:
            origin = normalise(req.origin)
        except OriginError:
            origin = None
        if origin and "*" in origin:
            origin = None
    else:
        origin = normalise(req.origin) if matches(req.origin, widget_repo.origins(row)) else None
    if origin is None:
        return Response(status_code=204)
    seen = req.session_id and db.scalar(
        select(AccessLog.id).where(
            AccessLog.bot_id == bot.id,
            AccessLog.event == "WIDGET_OPENED",
            AccessLog.session_id == req.session_id,
        )
    )
    if not seen:
        logs.add(db, bot.id, req.session_id, "WIDGET_OPENED", detail=origin)
        db.commit()
    return Response(status_code=204)


_TEST_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")

TEST_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Widget test</title>
<style>body{{margin:0;font:15px system-ui,sans-serif;color:#334155;background:#f8fafc}}
main{{max-width:640px;margin:0 auto;padding:32px 16px}}#mebot-chat{{margin-top:24px}}</style>
</head>
<body>
<main>
<h1>Widget test page</h1>
<p>A blank host page for trying the widget. Only you (signed in) can open it.</p>
{target}
</main>
{loader}
</body>
</html>
"""


@router.get("/widget-test", response_class=HTMLResponse)
def widget_test(
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    bot = bots.get_primary(db)
    attrs = [f'data-bot="{escape(bot.slug)}"']
    q = request.query_params
    if _TEST_COLOR.match(q.get("color", "")):
        attrs.append(f'data-color="{q["color"].lower()}"')
    if q.get("position") in ("left", "right"):
        attrs.append(f'data-position="{q["position"]}"')
    if q.get("open") in ("1", "true"):
        attrs.append('data-open="true"')
    inline = q.get("mode") == "inline"
    if inline:
        attrs.append('data-mode="inline" data-target="#mebot-chat"')
    loader = f'<script src="/widget/v1.js" {" ".join(attrs)} async></script>'
    return HTMLResponse(
        TEST_PAGE.format(target='<div id="mebot-chat"></div>' if inline else "", loader=loader),
        headers={
            # The admin Widget page shows this in its live preview iframe.
            "Content-Security-Policy": "frame-ancestors 'self'",
            "X-Frame-Options": "SAMEORIGIN",
            "Cache-Control": "no-store",
        },
    )
