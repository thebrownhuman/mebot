"""Request-scoped dependencies."""

from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from mebot.auth.cookies import CLEAR_SESSION_HEADER, SESSION_COOKIE
from mebot.auth.csrf import require_csrf
from mebot.config import Settings
from mebot.db import get_db
from mebot.errors import ApiError
from mebot.models import Admin, Bot
from mebot.repos import admin_sessions, admins, bots


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


# Hosted: these paths always act on the logged-in owner's bot, never on a slug/host.
OWNER_PATHS = ("/api/admin", "/api/auth", "/api/hosted", "/widget-test")


def _not_found() -> ApiError:
    return ApiError(404, "BOT_UNAVAILABLE", "This assistant is unavailable.")


def get_current_bot(request: Request, db: Session = Depends(get_db)) -> Bot:
    """The bot this request acts on.

    Single mode: the one bot this install serves (created on first use).
    Hosted mode: owner paths -> the logged-in admin's bot; public paths -> the bot the
    tenant middleware resolved from /b/{ref} or the subdomain, falling back to the
    logged-in owner's own bot (so "Try your bot" works on the main domain). Anything
    else is a 404.
    """
    settings: Settings = request.app.state.settings
    if not settings.hosted:
        return bots.get_primary(db)
    tenant_bot_id = request.scope.get("state", {}).get("tenant_bot_id")
    owner_path = request.url.path.startswith(OWNER_PATHS)
    if tenant_bot_id and not owner_path:
        bot = bots.get(db, tenant_bot_id)
        if bot is None:
            raise _not_found()
        return bot
    current = _admin_from_cookie(request, db)
    if current is None:
        if owner_path:
            raise ApiError(401, "UNAUTHENTICATED", "Login required")
        raise _not_found()
    bot = bots.get(db, current.admin.bot_id)
    if bot is None or (tenant_bot_id and tenant_bot_id != bot.id):
        raise _not_found()
    return bot


def client_ip(request: Request) -> str | None:
    settings: Settings = request.app.state.settings
    if settings.trust_proxy:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            # Last hop is the one our proxy appended; earlier entries are client-controlled.
            return fwd.split(",")[-1].strip() or None
    return request.client.host if request.client else None


def require_setup_done(request: Request, db: Session = Depends(get_db)) -> None:
    # Hosted: there is no global setup; each tenant's bot is resolved (and gated) per
    # request by get_current_bot / the tenant middleware.
    if request.app.state.settings.hosted:
        return
    if not admins.exists(db):
        raise ApiError(503, "SETUP_REQUIRED", "Setup has not been completed")


@dataclass
class CurrentAdmin:
    admin: Admin
    token: str


def _admin_from_cookie(request: Request, db: Session) -> CurrentAdmin | None:
    """The logged-in admin, resolved once per request (resolving slides the expiry)."""
    cached = request.scope.get("state", {}).get("_current_admin", False)
    if cached is not False:
        return cached
    token = request.cookies.get(SESSION_COOKIE)
    session = admin_sessions.resolve(db, token) if token else None
    admin = admins.get(db, session.admin_id) if session else None
    if admin is not None and request.app.state.settings.hosted:
        # Sessions bind to the tenant they were created for, and die with it.
        bot = bots.get(db, admin.bot_id) if admin.bot_id else None
        if bot is None or session.bot_id != admin.bot_id or bot.status != "active":
            admin = None
    current = CurrentAdmin(admin=admin, token=token) if admin is not None else None
    request.state._current_admin = current
    return current


def get_current_admin(request: Request, db: Session = Depends(get_db)) -> CurrentAdmin:
    current = _admin_from_cookie(request, db)
    if current is None:
        token = request.cookies.get(SESSION_COOKIE)
        headers = {"set-cookie": CLEAR_SESSION_HEADER} if token else None
        raise ApiError(401, "UNAUTHENTICATED", "Login required", headers=headers)
    return current


def csrf_on_mutation(request: Request) -> None:
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        require_csrf(request)
