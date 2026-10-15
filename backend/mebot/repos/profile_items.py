"""Bot-scoped CRUD for the structured profile. Every query filters on bot_id and
excludes soft-deleted rows."""

import json
from datetime import UTC

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mebot.models import ProfileIdentity, ProfileNotes, utcnow
from mebot.profile.schemas import IdentityIn, NotesIn
from mebot.profile.sections import Section

_HIDDEN = {"bot_id", "deleted_at"}


def _iso(dt) -> str | None:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def serialize(sec: Section | None, row) -> dict:
    out = {}
    json_fields = sec.json_fields if sec else ()
    for col in row.__table__.columns:
        if col.name in _HIDDEN:
            continue
        v = getattr(row, col.name)
        if col.name in json_fields:
            v = json.loads(v or "[]")
        elif col.name in ("created_at", "updated_at"):
            v = _iso(v)
        out[col.name] = v
    return out


def _apply(sec: Section, row, data: BaseModel) -> None:
    for k, v in data.model_dump().items():
        if k in sec.json_fields:
            v = json.dumps(v)
        setattr(row, k, v)


def _active(model, bot_id: str):
    return select(model).where(model.bot_id == bot_id, model.deleted_at.is_(None))


def list_items(db: Session, sec: Section, bot_id: str) -> list:
    m = sec.model
    return list(db.scalars(_active(m, bot_id).order_by(m.sort_order, m.created_at, m.id)))


def count(db: Session, sec: Section, bot_id: str) -> int:
    m = sec.model
    return db.scalar(select(func.count(m.id)).where(m.bot_id == bot_id, m.deleted_at.is_(None)))


def get(db: Session, sec: Section, bot_id: str, item_id: str):
    return db.scalar(_active(sec.model, bot_id).where(sec.model.id == item_id))


def create(db: Session, sec: Section, bot_id: str, data: BaseModel):
    m = sec.model
    top = db.scalar(
        select(func.max(m.sort_order)).where(m.bot_id == bot_id, m.deleted_at.is_(None))
    )
    now = utcnow()
    row = m(bot_id=bot_id, sort_order=0 if top is None else top + 1, created_at=now, updated_at=now)
    _apply(sec, row, data)
    db.add(row)
    db.flush()
    return row


def update(db: Session, sec: Section, row, data: BaseModel):
    _apply(sec, row, data)
    row.updated_at = utcnow()
    db.flush()
    return row


def soft_delete(db: Session, row) -> None:
    row.deleted_at = row.updated_at = utcnow()
    db.flush()


def reorder(db: Session, sec: Section, bot_id: str, ids: list[str]) -> bool:
    """Apply a new order. ids must be exactly the bot's active ids, each once."""
    rows = {r.id: r for r in list_items(db, sec, bot_id)}
    if len(ids) != len(set(ids)) or set(ids) != set(rows):
        return False
    now = utcnow()
    for i, item_id in enumerate(ids):
        rows[item_id].sort_order = i
        rows[item_id].updated_at = now
    db.flush()
    return True


# --- singletons ----------------------------------------------------------------------


def _singleton(db: Session, model, bot_id: str):
    return db.scalar(_active(model, bot_id))


def _put_singleton(db: Session, model, bot_id: str, data: BaseModel):
    row = _singleton(db, model, bot_id)
    now = utcnow()
    if row is None:
        row = model(bot_id=bot_id, created_at=now)
        db.add(row)
    for k, v in data.model_dump().items():
        setattr(row, k, v)
    row.updated_at = now
    db.flush()
    return row


def get_identity(db: Session, bot_id: str) -> ProfileIdentity | None:
    return _singleton(db, ProfileIdentity, bot_id)


def put_identity(db: Session, bot_id: str, data: IdentityIn) -> ProfileIdentity:
    return _put_singleton(db, ProfileIdentity, bot_id, data)


def get_notes(db: Session, bot_id: str) -> ProfileNotes | None:
    return _singleton(db, ProfileNotes, bot_id)


def put_notes(db: Session, bot_id: str, data: NotesIn) -> ProfileNotes:
    return _put_singleton(db, ProfileNotes, bot_id, data)
