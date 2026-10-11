import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mebot.models import ChatSession, Message


def create(db: Session, bot_id: str, recruiter_name: str | None) -> str:
    sid = uuid.uuid4().hex
    db.add(ChatSession(id=sid, bot_id=bot_id, recruiter_name=recruiter_name))
    db.flush()
    return sid


def get(db: Session, bot_id: str, session_id: str) -> ChatSession | None:
    return db.scalar(
        select(ChatSession).where(ChatSession.id == session_id, ChatSession.bot_id == bot_id)
    )


def list_with_turns(db: Session, bot_id: str) -> list[dict]:
    turns = (
        select(Message.session_id, func.count(Message.id).label("turns"))
        .where(Message.bot_id == bot_id)
        .group_by(Message.session_id)
        .subquery()
    )
    rows = db.execute(
        select(ChatSession, func.coalesce(turns.c.turns, 0))
        .outerjoin(turns, turns.c.session_id == ChatSession.id)
        .where(ChatSession.bot_id == bot_id)
        .order_by(ChatSession.started_at.desc())
    ).all()
    return [
        {
            "id": s.id,
            "recruiter_name": s.recruiter_name,
            "started_at": s.started_at.timestamp(),
            "turns": n,
        }
        for s, n in rows
    ]


def messages(db: Session, bot_id: str, session_id: str) -> list[Message]:
    return list(
        db.scalars(
            select(Message)
            .where(Message.bot_id == bot_id, Message.session_id == session_id)
            .order_by(Message.created_at, Message.id)
        )
    )


def add_message(db: Session, bot_id: str, session_id: str, role: str, content: str) -> None:
    db.add(Message(bot_id=bot_id, session_id=session_id, role=role, content=content))
    db.flush()
