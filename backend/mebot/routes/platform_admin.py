"""Platform operator API (hosted mode): /api/platform/*.

Metadata and account actions only. There is deliberately no route that returns keys,
prompts, profiles, contacts or conversations; tests/test_platform.py enumerates these
routes and asserts that. Every state-changing action is written to the audit log.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from mebot.auth import passwords
from mebot.auth.cookies import is_secure, set_csrf_cookie
from mebot.auth.csrf import CSRF_COOKIE, require_csrf
from mebot.billing import service as billing
from mebot.config import Settings
from mebot.db import get_db
from mebot.deps import client_ip, get_settings
from mebot.errors import ApiError
from mebot.hosted import mailer
from mebot.hosted import operator as op
from mebot.models import Admin, Bot, Invite, PlatformAdmin, utcnow
from mebot.repos import account_tokens, admin_sessions, bots, invites
from mebot.routes.hosted_accounts import require_hosted

router = APIRouter(prefix="/api/platform", dependencies=[Depends(require_hosted)])


def current_operator(request: Request, db: Session = Depends(get_db)) -> PlatformAdmin:
    admin = op.resolve(db, request.cookies.get(op.COOKIE))
    if admin is None:
        raise ApiError(401, "UNAUTHENTICATED", "Operator login required")
    return admin


operator_only = [Depends(current_operator), Depends(require_csrf)]


class LoginReq(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=passwords.MAX_LENGTH)


class ReasonReq(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class InviteReq(BaseModel):
    note: str | None = Field(default=None, max_length=200)
    days: int = Field(default=30, ge=0, le=365)


def _tenant(db: Session, bot_id: str) -> Bot:
    bot = bots.get(db, bot_id)
    if bot is None:
        raise ApiError(404, "NOT_FOUND", "Tenant not found")
    return bot


def _owner(db: Session, bot_id: str) -> Admin | None:
    return db.scalar(select(Admin).where(Admin.bot_id == bot_id, Admin.deleted_at.is_(None)))


def _base(request: Request, settings: Settings) -> str:
    return (settings.public_url or str(request.base_url)).rstrip("/")


# --- auth ----------------------------------------------------------------------------


@router.post("/auth/login", status_code=204, dependencies=[Depends(require_csrf)])
async def login(
    req: LoginReq,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    limiter = request.app.state.login_limiter
    ip = client_ip(request)
    key = f"platform:{req.email}"
    wait = limiter.retry_after(ip, key)
    if wait is not None:
        raise ApiError(
            429, "RATE_LIMITED", "Too many attempts.", headers={"Retry-After": str(wait)}
        )
    admin = op.get_by_email(db, req.email)
    if admin is None:
        await run_in_threadpool(passwords.dummy_verify, req.password)
        ok = False
    else:
        ok = await run_in_threadpool(passwords.verify_password, admin.password_hash, req.password)
    if not ok:
        limiter.record_failure(ip, key)
        raise ApiError(401, "INVALID_CREDENTIALS", "Invalid email or password")
    token = op.create_session(db, admin.id)
    op.audit(db, admin.id, "login")
    db.commit()
    response.set_cookie(
        op.COOKIE,
        token,
        max_age=int(op.TTL.total_seconds()),
        path="/",
        samesite="strict",
        secure=is_secure(request, settings),
        httponly=True,
    )
    if CSRF_COOKIE not in request.cookies:
        set_csrf_cookie(response, request, settings)


@router.post("/auth/logout", status_code=204, dependencies=[Depends(require_csrf)])
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(op.COOKIE)
    if token:
        op.revoke(db, token)
        db.commit()
    response.delete_cookie(op.COOKIE, path="/", samesite="strict", httponly=True)


@router.get("/auth/me")
def me(admin: PlatformAdmin = Depends(current_operator)):
    return {"email": admin.email}


# --- tenants -------------------------------------------------------------------------


@router.get("/tenants", dependencies=[Depends(current_operator)])
def tenants(db: Session = Depends(get_db)):
    return {"items": [t for t in op.tenants(db) if t["status"] != "pending"]}


@router.get("/signups", dependencies=[Depends(current_operator)])
def signups(db: Session = Depends(get_db)):
    """Invite-mode sign-ups without a code, waiting for approval."""
    return {"items": [t for t in op.tenants(db) if t["status"] == "pending"]}


@router.post("/tenants/{bot_id}/approve", dependencies=operator_only)
async def approve(
    bot_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor: PlatformAdmin = Depends(current_operator),
    settings: Settings = Depends(get_settings),
):
    bot = _tenant(db, bot_id)
    if bot.status != "pending":
        raise ApiError(409, "NOT_PENDING", "This sign-up isn't waiting for approval.")
    bot.status = "active"
    bot.approved_at = utcnow()
    owner = _owner(db, bot.id)
    if owner is not None:
        billing.start_trial(db, settings, request.app.state.secret_key, bot.id, owner.email)
    op.audit(db, actor.id, "approve", bot.id)
    db.commit()
    if owner is not None:
        base = _base(request, settings)
        await mailer.deliver(
            request.app.state.mailer, mailer.approved_mail(owner.email, f"{base}/admin/login")
        )
    return {"status": bot.status}


@router.post("/tenants/{bot_id}/suspend", dependencies=operator_only)
def suspend(
    bot_id: str,
    req: ReasonReq,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: PlatformAdmin = Depends(current_operator),
):
    bot = _tenant(db, bot_id)
    if bot.status not in ("active", "pending"):
        raise ApiError(409, "NOT_ACTIVE", "Only active tenants can be suspended.")
    bot.status = "suspended"
    bot.status_reason = req.reason.strip()
    bot.updated_at = utcnow()
    admin_sessions.revoke_for_bot(db, bot.id)
    op.audit(db, actor.id, "suspend", bot.id, req.reason.strip())
    db.commit()
    background.add_task(op.ping, request.app.state.settings, f"mebot: suspended {bot.slug}")
    return {"status": bot.status}


@router.post("/tenants/{bot_id}/unsuspend", dependencies=operator_only)
def unsuspend(
    bot_id: str, db: Session = Depends(get_db), actor: PlatformAdmin = Depends(current_operator)
):
    bot = _tenant(db, bot_id)
    if bot.status != "suspended":
        raise ApiError(409, "NOT_SUSPENDED", "This tenant isn't suspended.")
    bot.status = "active"
    bot.status_reason = None
    bot.updated_at = utcnow()
    op.audit(db, actor.id, "unsuspend", bot.id)
    db.commit()
    return {"status": bot.status}


@router.post("/tenants/{bot_id}/delete", dependencies=operator_only)
def delete_tenant(
    bot_id: str,
    req: ReasonReq,
    db: Session = Depends(get_db),
    actor: PlatformAdmin = Depends(current_operator),
):
    """Same path as an owner's own deletion: offline now, purged after the grace period."""
    bot = _tenant(db, bot_id)
    now = utcnow()
    bot.status = "deleted"
    bot.status_reason = req.reason.strip()
    bot.deletion_requested_at = bot.deletion_requested_at or now
    owner = _owner(db, bot.id)
    if owner is not None:
        owner.deleted_at = now
    admin_sessions.revoke_for_bot(db, bot.id)
    op.audit(db, actor.id, "delete", bot.id, req.reason.strip())
    db.commit()
    return {"status": bot.status}


@router.post("/tenants/{bot_id}/resend-verification", dependencies=operator_only)
async def resend_verification(
    bot_id: str,
    request: Request,
    db: Session = Depends(get_db),
    actor: PlatformAdmin = Depends(current_operator),
    settings: Settings = Depends(get_settings),
):
    bot = _tenant(db, bot_id)
    owner = _owner(db, bot.id)
    if owner is None or owner.email_verified_at is not None:
        raise ApiError(409, "ALREADY_VERIFIED", "Nothing to resend.")
    token = account_tokens.issue(db, "verify", owner.id)
    op.audit(db, actor.id, "resend_verification", bot.id)
    db.commit()
    link = f"{_base(request, settings)}/verify?token={token}"
    await mailer.deliver(request.app.state.mailer, mailer.verify_mail(owner.email, link))
    return {"sent": True}


# --- invites and audit ------------------------------------------------------------------


@router.get("/invites", dependencies=[Depends(current_operator)])
def list_invites(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Invite).where(Invite.deleted_at.is_(None)).order_by(Invite.created_at.desc())
    )
    return {
        "items": [
            {
                "id": i.id,
                "note": i.note,
                "created_at": i.created_at.isoformat(),
                "expires_at": i.expires_at.isoformat() if i.expires_at else None,
                "used_at": i.used_at.isoformat() if i.used_at else None,
            }
            for i in rows
        ]
    }


@router.post("/invites", status_code=201, dependencies=operator_only)
def create_invite(
    req: InviteReq, db: Session = Depends(get_db), actor: PlatformAdmin = Depends(current_operator)
):
    code = invites.create(db, note=req.note, days=req.days or None)
    op.audit(db, actor.id, "invite_created", None, req.note)
    db.commit()
    return {"code": code}  # shown once; only its hash is stored


@router.delete("/invites/{invite_id}", status_code=204, dependencies=operator_only)
def revoke_invite(
    invite_id: str, db: Session = Depends(get_db), actor: PlatformAdmin = Depends(current_operator)
):
    row = db.get(Invite, invite_id)
    if row is None or row.deleted_at is not None:
        raise ApiError(404, "NOT_FOUND", "Invite not found")
    row.deleted_at = utcnow()
    op.audit(db, actor.id, "invite_revoked", None, row.note)
    db.commit()


@router.get("/audit", dependencies=[Depends(current_operator)])
def audit_log(db: Session = Depends(get_db)):
    return {"items": op.audit_page(db)}
