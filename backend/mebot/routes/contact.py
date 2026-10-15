"""Recruiters leave their contact details for the owner (POST /api/contact)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, BeforeValidator, EmailStr, Field, StringConstraints
from sqlalchemy.orm import Session

from mebot.db import get_db
from mebot.deps import client_ip, get_current_bot
from mebot.errors import ApiError
from mebot.models import Bot, Contact
from mebot.repos import logs, sessions
from mebot.telegram import events

router = APIRouter(prefix="/api")


def _blank_none(v):
    return v.strip() or None if isinstance(v, str) else v


Opt = Annotated[
    Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None,
    BeforeValidator(_blank_none),
]


class ContactIn(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    email: EmailStr = Field(max_length=254)
    company: Opt = None
    role: Opt = None
    note: Annotated[
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None,
        BeforeValidator(_blank_none),
    ] = None
    # Honeypot: hidden in the form, so only bots fill it in.
    website: str | None = Field(default=None, max_length=500)


@router.post("/contact", status_code=201)
def leave_contact(
    req: ContactIn,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    ip = client_ip(request)
    limiter = request.app.state.contact_limiter
    wait = limiter.hit(request.app.state.chat_limiter.ip_key(ip))
    if wait is not None:
        raise ApiError(
            429,
            "RATE_LIMITED",
            "You've already left your details. Please try again later.",
            headers={"Retry-After": str(wait)},
        )
    if req.website:
        logs.add(db, bot.id, None, "CONTACT_SPAM")
        db.commit()
        return {"id": None}  # looks like success to the bot; nothing stored or sent
    sid = req.session_id if req.session_id and sessions.get(db, bot.id, req.session_id) else None
    c = Contact(
        bot_id=bot.id,
        session_id=sid,
        name=req.name,
        email=str(req.email),
        company=req.company,
        role=req.role,
        note=req.note,
    )
    db.add(c)
    db.flush()
    logs.add(db, bot.id, sid, "CONTACT_LEFT")
    events.contact(db, bot.id, c)
    db.commit()
    return {"id": c.id}
