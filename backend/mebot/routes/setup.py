import re
import secrets

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mebot.auth import passwords
from mebot.auth.cookies import set_csrf_cookie, set_login_cookies
from mebot.auth.csrf import CSRF_COOKIE, require_csrf
from mebot.config import Settings
from mebot.db import get_db
from mebot.deps import client_ip, get_settings
from mebot.errors import ApiError
from mebot.repos import admin_sessions, admins, bots

router = APIRouter(prefix="/api/setup")

SLUG_RE = re.compile(r"^[a-z0-9-]{3,40}$")
RESERVED_SLUGS = {"admin", "setup", "api", "widget", "assets"}


class SetupReq(BaseModel):
    email: EmailStr
    password: str = Field(min_length=passwords.MIN_LENGTH, max_length=passwords.MAX_LENGTH)
    bot_name: str = Field(max_length=80)
    bot_slug: str
    registration_consent: bool = False
    setup_token: str | None = None

    @field_validator("bot_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("bot name must not be empty")
        return v

    @field_validator("bot_slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError("use 3-40 lowercase letters, digits or hyphens")
        if v in RESERVED_SLUGS:
            raise ValueError(f"'{v}' is reserved")
        return v


def _completed() -> ApiError:
    return ApiError(409, "SETUP_COMPLETED", "Setup has already been completed")


@router.get("/status")
def status(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    # Hand out the CSRF cookie early so the setup form can double-submit it.
    if CSRF_COOKIE not in request.cookies:
        set_csrf_cookie(response, request, settings)
    return {"setup_required": not admins.exists(db)}


@router.post("", status_code=201, dependencies=[Depends(require_csrf)])
def setup(
    req: SetupReq,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if settings.setup_token and not secrets.compare_digest(
        (req.setup_token or "").encode(), settings.setup_token.encode()
    ):
        raise ApiError(403, "SETUP_TOKEN_INVALID", "Invalid setup token")
    if admins.exists(db):
        raise _completed()

    password_hash = passwords.hash_password(req.password)  # slow: do it before locking
    bot = bots.get_or_create_default(db)
    try:
        if not bots.claim_setup(db, bot):
            db.rollback()
            raise _completed()
        bot.name = req.bot_name
        bot.slug = req.bot_slug
        bot.registration_consent = req.registration_consent
        admin = admins.create(db, req.email, password_hash)
        token = admin_sessions.create(
            db, admin.id, ip=client_ip(request), user_agent=request.headers.get("user-agent")
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _completed() from None

    set_login_cookies(response, request, settings, token)
    return {"email": admin.email, "bot_slug": bot.slug}
