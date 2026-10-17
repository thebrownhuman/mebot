"""Owner-only endpoints. Every route here needs setup done, a session, and CSRF on writes."""

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from mebot.db import get_db
from mebot.deps import csrf_on_mutation, get_current_admin, get_current_bot, require_setup_done
from mebot.errors import ApiError
from mebot.models import Bot, Contact, utcnow
from mebot.repos import logs, sessions

router = APIRouter(
    prefix="/api/admin",
    dependencies=[
        Depends(require_setup_done),
        Depends(get_current_admin),
        Depends(csrf_on_mutation),
    ],
)


def _deprecated(response: Response) -> None:
    # Superseded by /api/admin/conversations; kept for one release.
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = '</api/admin/conversations>; rel="successor-version"'


@router.get("/sessions", deprecated=True, dependencies=[Depends(_deprecated)])
def list_sessions(db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    return sessions.list_with_turns(db, bot.id)


@router.get(
    "/sessions/{sid}/messages", deprecated=True, dependencies=[Depends(_deprecated)]
)
def session_messages(sid: str, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    if sessions.get(db, bot.id, sid) is None:
        raise HTTPException(404, "Unknown session")
    return [
        {"role": m.role, "content": m.content, "ts": m.created_at.timestamp()}
        for m in sessions.messages(db, bot.id, sid)
    ]


@router.get("/unanswered")
def read_unanswered(
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    return {"items": logs.unanswered(db, bot.id, limit)}


def _contact(c: Contact) -> dict:
    return {
        "id": c.id,
        "session_id": c.session_id,
        "name": c.name,
        "email": c.email,
        "company": c.company,
        "role": c.role,
        "note": c.note,
        "created_at": c.created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


@router.get("/contacts")
def list_contacts(db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    rows = db.scalars(
        select(Contact)
        .where(Contact.bot_id == bot.id, Contact.deleted_at.is_(None))
        .order_by(Contact.created_at.desc(), Contact.id)
    )
    return {"items": [_contact(c) for c in rows]}


@router.delete("/contacts/{cid}", status_code=204)
def delete_contact(cid: str, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    c = db.get(Contact, cid)
    if c is None or c.bot_id != bot.id or c.deleted_at is not None:
        raise ApiError(404, "NOT_FOUND", "Contact not found")
    c.deleted_at = utcnow()
    db.commit()
    return Response(status_code=204)


@router.get("/log")
def read_log(
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    return logs.recent(db, bot.id, limit)
