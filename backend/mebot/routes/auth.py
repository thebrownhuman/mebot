from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mebot.auth import passwords
from mebot.auth.cookies import SESSION_COOKIE, clear_session_cookie, set_login_cookies
from mebot.auth.csrf import require_csrf
from mebot.config import Settings
from mebot.db import get_db
from mebot.deps import CurrentAdmin, client_ip, get_current_admin, get_current_bot, get_settings
from mebot.errors import ApiError
from mebot.limits import counters
from mebot.models import Bot
from mebot.repos import admin_sessions, admins, bots

router = APIRouter(prefix="/api/auth")


class LoginReq(BaseModel):
    # Plain str, not EmailStr: a malformed email must get the same 401 as a wrong one.
    email: str = Field(max_length=320)
    password: str = Field(max_length=passwords.MAX_LENGTH)


class PasswordReq(BaseModel):
    current_password: str = Field(max_length=passwords.MAX_LENGTH)
    new_password: str = Field(min_length=passwords.MIN_LENGTH, max_length=passwords.MAX_LENGTH)


@router.post("/login", status_code=204)
def login(
    req: LoginReq,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    limiter = request.app.state.login_limiter
    ip = client_ip(request)
    wait = limiter.retry_after(ip, req.email)
    if wait is not None:
        raise ApiError(
            429,
            "RATE_LIMITED",
            "Too many login attempts. Try again later.",
            headers={"Retry-After": str(wait)},
        )

    admin = admins.get_by_email(db, req.email)
    if admin is None:
        passwords.dummy_verify(req.password)
        ok = False
    else:
        ok = passwords.verify_password(admin.password_hash, req.password)
    if not ok:
        limiter.record_failure(ip, req.email)
        raise ApiError(401, "INVALID_CREDENTIALS", "Invalid email or password")
    if settings.hosted:
        bot = bots.get(db, admin.bot_id) if admin.bot_id else None
        if bot is not None and bot.status == "pending":
            raise ApiError(403, "PENDING_APPROVAL", "Your sign-up is waiting for approval.")
        if bot is None or bot.status != "active":
            raise ApiError(401, "INVALID_CREDENTIALS", "Invalid email or password")

    admin_sessions.purge_expired(db)
    token = admin_sessions.create(
        db,
        admin.id,
        ip_hash=counters.stored_ip_hash(request.app.state.secret_key, ip),
        user_agent=request.headers.get("user-agent"),
        bot_id=admin.bot_id,
    )
    db.commit()
    set_login_cookies(response, request, settings, token)


@router.post("/logout", status_code=204, dependencies=[Depends(require_csrf)])
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        admin_sessions.revoke(db, token)
    clear_session_cookie(response)


@router.get("/me")
def me(
    current: CurrentAdmin = Depends(get_current_admin),
    bot: Bot = Depends(get_current_bot),
):
    return {"email": current.admin.email, "bot_name": bot.name, "bot_slug": bot.slug}


@router.post("/password", status_code=204, dependencies=[Depends(require_csrf)])
def change_password(
    req: PasswordReq,
    current: CurrentAdmin = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if not passwords.verify_password(current.admin.password_hash, req.current_password):
        raise ApiError(400, "INVALID_PASSWORD", "Current password is incorrect")
    admins.set_password_hash(db, current.admin, passwords.hash_password(req.new_password))
    db.commit()
    admin_sessions.revoke_all(db, current.admin.id, except_token=current.token)
