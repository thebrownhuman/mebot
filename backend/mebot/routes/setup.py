import re
import secrets

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
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
from mebot.llm import service as llm
from mebot.llm.providers import PROVIDERS
from mebot.profile.schemas import IdentityIn
from mebot.repos import admin_sessions, admins, bots
from mebot.repos import profile_items as profile

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
    llm: llm.LLMInput

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


class LLMProbeReq(llm.LLMInput):
    setup_token: str | None = None


def _completed() -> ApiError:
    return ApiError(409, "SETUP_COMPLETED", "Setup has already been completed")


def _setup_limit(request: Request) -> None:
    """10 attempts / 15 min per IP across setup and probes (bad tokens count too)."""
    wait = request.app.state.setup_limiter.retry_after(client_ip(request) or "?")
    if wait is not None:
        raise ApiError(
            429,
            "RATE_LIMITED",
            "Too many attempts. Try again in a few minutes.",
            headers={"Retry-After": str(wait)},
        )


def _count_attempt(request: Request) -> None:
    request.app.state.setup_limiter.record(client_ip(request) or "?")


def _check_setup_token(request: Request, settings: Settings, given: str | None) -> None:
    _setup_limit(request)
    if settings.setup_token and not secrets.compare_digest(
        (given or "").encode(), settings.setup_token.encode()
    ):
        _count_attempt(request)
        raise ApiError(403, "SETUP_TOKEN_INVALID", "Invalid setup token")


def _probe_guard(request: Request, db: Session, settings: Settings, token: str | None) -> None:
    """Pre-setup LLM probes: only while setup is pending, token-gated, rate limited.

    They make the server call an owner-supplied URL, so keep the window narrow.
    """
    _check_setup_token(request, settings, token)
    if admins.exists(db):
        raise _completed()
    _count_attempt(request)  # each probe is an outbound call: it uses the budget


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


@router.get("/llm-providers")
def providers():
    return {"providers": [p.public() for p in PROVIDERS]}


@router.post("/llm-test", dependencies=[Depends(require_csrf)])
async def llm_test(
    req: LLMProbeReq,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _probe_guard(request, db, settings, req.setup_token)
    llm.validate(req)
    result = await llm.run_test(llm.resolve_input(req, settings))
    return {"ok": result.ok, "latency_ms": result.latency_ms}


@router.post("/llm-models", dependencies=[Depends(require_csrf)])
async def llm_models(
    req: LLMProbeReq,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _probe_guard(request, db, settings, req.setup_token)
    return {"models": await llm.list_models(llm.resolve_input(req, settings))}


@router.post("", status_code=201, dependencies=[Depends(require_csrf)])
async def setup(
    req: SetupReq,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _check_setup_token(request, settings, req.setup_token)
    if admins.exists(db):
        raise _completed()

    llm.validate(req.llm, prefix="llm.")
    llm_cfg = llm.resolve_input(req.llm, settings)
    await llm.run_test(llm_cfg)  # raises 422 LLM_TEST_FAILED; nothing created yet

    # Slow (argon2): keep it off the event loop and before taking the write lock.
    password_hash = await run_in_threadpool(passwords.hash_password, req.password)
    bot = bots.get_or_create_default(db)
    try:
        if not bots.claim_setup(db, bot):
            db.rollback()
            raise _completed()
        bot.name = req.bot_name
        bot.slug = req.bot_slug
        bot.registration_consent = req.registration_consent
        admin = admins.create(db, req.email, password_hash)
        llm.store(db, bot.id, llm_cfg, request.app.state.secret_key)
        if profile.get_identity(db, bot.id) is None:
            # The bot name is usually the owner's name: a starting point for Identity.
            profile.put_identity(db, bot.id, IdentityIn(full_name=req.bot_name))
        token = admin_sessions.create(
            db, admin.id, ip=client_ip(request), user_agent=request.headers.get("user-agent")
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _completed() from None

    set_login_cookies(response, request, settings, token)
    return {"email": admin.email, "bot_slug": bot.slug}
