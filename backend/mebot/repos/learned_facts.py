"""learned_facts access. Every query filters on bot_id; soft-deleted rows are excluded."""

from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from mebot.models import LearnedFact

MAX_ACTIVE = 200  # approved learned facts rendered into the prompt
STATUSES = ("pending", "approved", "rejected")


def _iso(dt) -> str | None:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def serialize(row: LearnedFact, current_value: str | None = None) -> dict:
    return {
        "id": row.id,
        "open_question_id": row.open_question_id,
        "question": row.question,
        "answer_raw": row.answer_raw,
        "fact_text": row.fact_text,
        "status": row.status,
        "source": row.source,
        "suggested_section": row.suggested_section,
        "suggested_field": row.suggested_field,
        "suggested_value": row.suggested_value,
        "current_value": current_value,
        "needs_review": row.needs_review,
        "approved_at": _iso(row.approved_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def get(db: Session, bot_id: str, fact_id: str) -> LearnedFact | None:
    return db.scalar(
        select(LearnedFact).where(
            LearnedFact.bot_id == bot_id,
            LearnedFact.id == fact_id,
            LearnedFact.deleted_at.is_(None),
        )
    )


def list_(db: Session, bot_id: str, status: str | None = None, limit: int = 500):
    q = select(LearnedFact).where(LearnedFact.bot_id == bot_id, LearnedFact.deleted_at.is_(None))
    if status:
        q = q.where(LearnedFact.status == status)
    return list(db.scalars(q.order_by(LearnedFact.created_at.desc(), LearnedFact.id).limit(limit)))


def active_learned(db: Session, bot_id: str, limit: int = MAX_ACTIVE) -> list[LearnedFact]:
    """Approved, not deleted, kept as free-text facts (identity writes live on the
    identity page instead), newest first."""
    q = (
        select(LearnedFact)
        .where(
            LearnedFact.bot_id == bot_id,
            LearnedFact.deleted_at.is_(None),
            LearnedFact.status == "approved",
            LearnedFact.suggested_section == "learned",
        )
        .order_by(LearnedFact.approved_at.desc(), LearnedFact.id)
        .limit(limit)
    )
    return list(db.scalars(q))


def count_active_learned(db: Session, bot_id: str) -> int:
    return len(active_learned(db, bot_id, limit=10_000))
