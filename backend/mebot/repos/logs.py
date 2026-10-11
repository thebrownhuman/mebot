from sqlalchemy import select
from sqlalchemy.orm import Session

from mebot.models import AccessLog


def add(
    db: Session,
    bot_id: str,
    session_id: str | None,
    event: str,
    detail: str | None = None,
    ip: str | None = None,
) -> None:
    db.add(AccessLog(bot_id=bot_id, session_id=session_id, event=event, detail=detail, ip=ip))
    db.flush()


def recent(db: Session, bot_id: str, limit: int = 100) -> list[dict]:
    rows = db.scalars(
        select(AccessLog)
        .where(AccessLog.bot_id == bot_id)
        .order_by(AccessLog.created_at.desc())
        .limit(limit)
    )
    return [
        {"event": r.event, "detail": r.detail, "ip": r.ip, "ts": r.created_at.timestamp()}
        for r in rows
    ]
