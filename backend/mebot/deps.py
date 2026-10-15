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


def get_current_bot(db: Session = Depends(get_db)) -> Bot:
    """Single mode: the one bot this install serves (created on first use).

    Hosted mode will resolve the bot from the request (slug/host) in a later feature.
    """
    return bots.get_primary(db)


def client_ip(request: Request) -> str | None:
    settings: Settings = request.app.state.settings
    if settings.trust_proxy:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            # Last hop is the one our proxy appended; earlier entries are client-controlled.
            return fwd.split(",")[-1].strip() or None
    return request.client.host if request.client else None


def require_setup_done(db: Session = Depends(get_db)) -> None:
    if not admins.exists(db):
        raise ApiError(503, "SETUP_REQUIRED", "Setup has not been completed")


@dataclass
class CurrentAdmin:
    admin: Admin
    token: str


def get_current_admin(request: Request, db: Session = Depends(get_db)) -> CurrentAdmin:
    token = request.cookies.get(SESSION_COOKIE)
    session = admin_sessions.resolve(db, token) if token else None
    admin = admins.get(db, session.admin_id) if session else None
    if admin is None:
        headers = {"set-cookie": CLEAR_SESSION_HEADER} if token else None
        raise ApiError(401, "UNAUTHENTICATED", "Login required", headers=headers)
    return CurrentAdmin(admin=admin, token=token)


def csrf_on_mutation(request: Request) -> None:
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        require_csrf(request)
