"""Hosted mode accounts: sign-up, e-mail verification, password reset.

All of /api/hosted/* is a 404 in single mode.

Enumeration: sign-up, resend and reset answer the same 202 whether or not the e-mail has
an account (an existing owner gets an "already registered" mail instead). Slugs are
public anyway, so a taken slug is a plain 409.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mebot import turnstile
from mebot.auth import passwords
from mebot.auth.csrf import require_csrf
from mebot.config import Settings
from mebot.db import get_db
from mebot.deps import client_ip, get_settings
from mebot.errors import ApiError
from mebot.hosted import mailer
from mebot.hosted.slugs import slug_error
from mebot.limits import counters
from mebot.models import utcnow
from mebot.repos import account_tokens, admin_sessions, admins, bots, invites


def require_hosted(request: Request) -> None:
    if not request.app.state.settings.hosted:
        raise ApiError(404, "NOT_FOUND", "Not Found")


router = APIRouter(prefix="/api/hosted", dependencies=[Depends(require_hosted)])

ACCEPTED = {"status": "check_your_email"}


class SignupReq(BaseModel):
    email: EmailStr
    password: str = Field(min_length=passwords.MIN_LENGTH, max_length=passwords.MAX_LENGTH)
    bot_name: str = Field(max_length=80)
    slug: str = Field(max_length=40)
    invite_code: str | None = Field(default=None, max_length=100)
    turnstile_token: str | None = Field(default=None, max_length=4096)

    @field_validator("bot_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = v.strip().lower()
        err = slug_error(v)
        if err:
            raise ValueError(err)
        return v


class EmailReq(BaseModel):
    email: str = Field(max_length=320)


class TokenReq(BaseModel):
    token: str = Field(max_length=200)


class ResetConfirmReq(TokenReq):
    new_password: str = Field(min_length=passwords.MIN_LENGTH, max_length=passwords.MAX_LENGTH)


def _base(request: Request, settings: Settings) -> str:
    return (settings.public_url or str(request.base_url)).rstrip("/")


def _limit(request: Request, bucket: str) -> None:
    """Per hashed IP (raw IPs are never kept, not even in memory keys)."""
    key = counters.stored_ip_hash(request.app.state.secret_key, client_ip(request)) or "?"
    wait = request.app.state.account_limiter.hit(f"{bucket}:{key}")
    if wait is not None:
        raise ApiError(
            429, "RATE_LIMITED", "Too many attempts. Try again later.",
            headers={"Retry-After": str(wait)},
        )  # fmt: skip


async def _turnstile(request: Request, settings: Settings, token: str | None) -> None:
    if not (settings.turnstile_site_key and settings.turnstile_secret_key):
        raise ApiError(503, "SIGNUP_UNAVAILABLE", "Sign-up isn't configured on this server.")
    if not token:
        raise ApiError(400, "TURNSTILE_REQUIRED", "Please complete the bot check.")
    try:
        ok = await turnstile.verify(settings.turnstile_secret_key, token, client_ip(request))
    except turnstile.TurnstileUnavailable:
        raise ApiError(503, "TURNSTILE_UNAVAILABLE", "Try again in a minute.") from None
    if not ok:
        raise ApiError(400, "TURNSTILE_FAILED", "The bot check failed. Please try again.")


@router.get("/config")
def config(settings: Settings = Depends(get_settings)):
    return {
        "signup_mode": settings.signup_mode,
        "turnstile_site_key": settings.turnstile_site_key,
        "hosted_domain": settings.hosted_domain,
    }


@router.post("/signup", status_code=202, dependencies=[Depends(require_csrf)])
async def signup(
    req: SignupReq,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if settings.signup_mode == "closed":
        raise ApiError(403, "SIGNUP_CLOSED", "Sign-up is closed.")
    _limit(request, "signup")
    await _turnstile(request, settings, req.turnstile_token)
    if settings.signup_mode == "invite" and not invites.valid(db, req.invite_code or ""):
        raise ApiError(400, "INVITE_INVALID", "That invite code isn't valid.")
    if bots.slug_taken(db, req.slug):
        raise ApiError(409, "SLUG_TAKEN", "That address is taken. Pick another.")
    base = _base(request, settings)
    existing = admins.get_by_email(db, req.email)
    if existing is not None:
        await mailer.deliver(
            request.app.state.mailer,
            mailer.already_registered_mail(
                existing.email, f"{base}/login", f"{base}/reset-password"
            ),
        )
        return ACCEPTED

    password_hash = await run_in_threadpool(passwords.hash_password, req.password)
    try:
        bot = bots.create(db, req.slug, req.bot_name)
        admin = admins.create(db, req.email, password_hash, bot_id=bot.id)
        if settings.signup_mode == "invite" and not invites.consume(
            db, req.invite_code or "", admin.id
        ):
            db.rollback()
            raise ApiError(400, "INVITE_INVALID", "That invite code isn't valid.")
        token = account_tokens.issue(db, "verify", admin.id)
        db.commit()
    except IntegrityError:  # concurrent sign-up took the slug or e-mail
        db.rollback()
        raise ApiError(409, "SLUG_TAKEN", "That address is taken. Pick another.") from None
    await mailer.deliver(
        request.app.state.mailer, mailer.verify_mail(admin.email, f"{base}/verify?token={token}")
    )
    return ACCEPTED


@router.post("/verify", status_code=204, dependencies=[Depends(require_csrf)])
def verify(req: TokenReq, db: Session = Depends(get_db)):
    admin_id = account_tokens.consume(db, "verify", req.token)
    admin = admins.get(db, admin_id) if admin_id else None
    if admin is None:
        db.rollback()
        raise ApiError(400, "TOKEN_INVALID", "This link is invalid or has expired.")
    if admin.email_verified_at is None:
        admin.email_verified_at = utcnow()
    db.commit()


@router.post("/verify/resend", status_code=202, dependencies=[Depends(require_csrf)])
async def resend(
    req: EmailReq,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _limit(request, "mail")
    admin = admins.get_by_email(db, req.email)
    if admin is not None and admin.email_verified_at is None:
        token = account_tokens.issue(db, "verify", admin.id)
        db.commit()
        link = f"{_base(request, settings)}/verify?token={token}"
        await mailer.deliver(request.app.state.mailer, mailer.verify_mail(admin.email, link))
    return ACCEPTED


@router.post("/password-reset", status_code=202, dependencies=[Depends(require_csrf)])
async def password_reset(
    req: EmailReq,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _limit(request, "mail")
    admin = admins.get_by_email(db, req.email)
    if admin is not None:
        token = account_tokens.issue(db, "reset", admin.id)
        db.commit()
        link = f"{_base(request, settings)}/reset-password?token={token}"
        await mailer.deliver(request.app.state.mailer, mailer.reset_mail(admin.email, link))
    return ACCEPTED


@router.post("/password-reset/confirm", status_code=204, dependencies=[Depends(require_csrf)])
async def password_reset_confirm(
    req: ResetConfirmReq, request: Request, db: Session = Depends(get_db)
):
    _limit(request, "reset-confirm")
    admin_id = account_tokens.consume(db, "reset", req.token)
    admin = admins.get(db, admin_id) if admin_id else None
    if admin is None:
        db.rollback()
        raise ApiError(400, "TOKEN_INVALID", "This link is invalid or has expired.")
    new_hash = await run_in_threadpool(passwords.hash_password, req.new_password)
    admins.set_password_hash(db, admin, new_hash)
    # Proves control of the inbox, so it also verifies the address.
    admin.email_verified_at = admin.email_verified_at or utcnow()
    db.commit()
    admin_sessions.revoke_all(db, admin.id)
