"""Seed conversations straight into the DB (no chat route, no LLM)."""

import uuid
from datetime import datetime, timedelta

from mebot.models import AccessLog, ChatSession, Contact, Message
from mebot.repos import bots


def bot_id(app) -> str:
    with app.state.session_factory() as db:
        b = bots.get_primary(db)
        db.commit()
        return b.id


def seed_session(
    app,
    started: datetime,
    turns: list[tuple[str, str]] | None = None,
    *,
    name: str | None = "Recruiter",
    events: list[tuple[str, str | None]] | None = None,
    contact: bool = False,
    origin: str | None = None,
    unanswered: bool = False,
    owner_reply: bool = False,
    gap: int = 30,
) -> str:
    """turns: [(role, content)], one every `gap` seconds from `started`.
    unanswered marks every assistant turn; owner_reply appends an owner message."""
    bid = bot_id(app)
    sid = uuid.uuid4().hex
    with app.state.session_factory() as db:
        db.add(ChatSession(id=sid, bot_id=bid, recruiter_name=name, started_at=started))
        t = started
        for role, content in turns or []:
            t += timedelta(seconds=gap)
            db.add(
                Message(
                    bot_id=bid,
                    session_id=sid,
                    role=role,
                    content=content,
                    created_at=t,
                    unanswered=unanswered and role == "assistant",
                )
            )
            if unanswered and role == "assistant":
                db.add(
                    AccessLog(
                        bot_id=bid, session_id=sid, event="UNANSWERED", detail="q", created_at=t
                    )
                )
        if owner_reply:
            t += timedelta(seconds=gap)
            db.add(
                Message(
                    bot_id=bid,
                    session_id=sid,
                    role="assistant",
                    content="owner here",
                    created_at=t,
                    from_owner=True,
                )
            )
            db.add(AccessLog(bot_id=bid, session_id=sid, event="OWNER_REPLIED", created_at=t))
        if origin:
            db.add(
                AccessLog(
                    bot_id=bid,
                    session_id=sid,
                    event="WIDGET_OPENED",
                    detail=origin,
                    created_at=started,
                )
            )
        for ev, detail in events or []:
            db.add(
                AccessLog(bot_id=bid, session_id=sid, event=ev, detail=detail, created_at=started)
            )
        if contact:
            db.add(
                Contact(
                    bot_id=bid,
                    session_id=sid,
                    name=name or "x",
                    email="r@example.com",
                    created_at=started,
                )
            )
            db.add(AccessLog(bot_id=bid, session_id=sid, event="CONTACT_LEFT", created_at=started))
        db.commit()
    return sid


def counts(app) -> dict[str, int]:
    from sqlalchemy import func, select

    with app.state.session_factory() as db:
        return {
            "sessions": db.scalar(select(func.count()).select_from(ChatSession)),
            "messages": db.scalar(select(func.count()).select_from(Message)),
            "contacts": db.scalar(select(func.count()).select_from(Contact)),
            "access_log": db.scalar(select(func.count()).select_from(AccessLog)),
        }
