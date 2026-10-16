"""The learning loop: propose a fact from the owner's answer, then approve / edit / reject.

Shared by the admin API and the Telegram buttons, so both behave identically. Errors are
``ApiError`` (the admin API returns them as is; Telegram shows the message).
"""

import re

from sqlalchemy.orm import Session

from mebot import persona
from mebot.errors import ApiError
from mebot.guard import personal
from mebot.learning import clean
from mebot.llm import service as llm
from mebot.models import Bot, LearnedFact, utcnow
from mebot.profile.schemas import IdentityIn
from mebot.repos import learned_facts, logs, open_questions
from mebot.repos import profile_items as profile

MAX_QUESTION = 500
MODES = ("replace", "keep_both")
_EDITABLE = ("fact_text", "field", "value")


def _identity_dict(db: Session, bot_id: str) -> dict:
    row = profile.get_identity(db, bot_id)
    return profile.serialize(None, row) if row else {}


def _bot_name(db: Session, bot_id: str) -> str | None:
    bot = db.get(Bot, bot_id)
    return bot.name if bot else None


def current_value(db: Session, bot_id: str, field: str | None) -> str | None:
    if not field or field not in clean.IDENTITY_FIELDS:
        return None
    return (_identity_dict(db, bot_id).get(field) or "").strip() or None


def serialize(db: Session, fact: LearnedFact) -> dict:
    field = fact.suggested_field if fact.suggested_section == "identity" else None
    return learned_facts.serialize(fact, current_value(db, fact.bot_id, field))


async def propose(
    db: Session,
    bot_id: str,
    secret_key: str,
    *,
    question: str,
    answer: str,
    source: str,
    open_question_id: str | None = None,
) -> LearnedFact:
    """Clean the owner's answer and store it as a pending fact (not yet known to the bot)."""
    answer = answer.strip()
    if not answer:
        raise ApiError(422, "VALIDATION_ERROR", "Write an answer first.")
    identity = _identity_dict(db, bot_id)
    name = persona.display_name(identity, _bot_name(db, bot_id))
    pronouns = identity.get("pronouns") or persona.DEFAULT_PRONOUNS
    _, _, cfg = llm.load(db, bot_id, secret_key)
    client = cfg.client() if cfg else None
    result = await clean.clean(
        client,
        cfg.model if cfg else "",
        question=question,
        answer=answer,
        name=name,
        pronouns=pronouns,
    )
    if result.rejected:
        raise ApiError(422, "PERSONAL_ANSWER", result.rejected)
    now = utcnow()
    fact = LearnedFact(
        bot_id=bot_id,
        open_question_id=open_question_id,
        question=question.strip()[:MAX_QUESTION],
        answer_raw=answer[: clean.MAX_ANSWER],
        fact_text=result.fact_text,
        suggested_section=result.section,
        suggested_field=result.field,
        suggested_value=result.value,
        status="pending",
        source=source,
        needs_review=result.needs_review,
        created_at=now,
        updated_at=now,
    )
    db.add(fact)
    db.flush()
    logs.add(db, bot_id, None, "fact_proposed", detail=source)
    return fact


def _require(db: Session, bot_id: str, fact_id: str) -> LearnedFact:
    fact = learned_facts.get(db, bot_id, fact_id)
    if fact is None:
        raise ApiError(404, "NOT_FOUND", "Fact not found")
    return fact


def _validate_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise ApiError(422, "VALIDATION_ERROR", "The fact can't be empty.")
    if len(text) > clean.MAX_FACT:
        raise ApiError(422, "VALIDATION_ERROR", f"Keep the fact under {clean.MAX_FACT} characters.")
    if personal.classify(text):
        raise ApiError(422, "PERSONAL_ANSWER", clean.REJECT_MESSAGE)
    return text


def _apply_edits(fact: LearnedFact, edits: dict) -> None:
    if edits.get("fact_text") is not None:
        fact.fact_text = _validate_text(edits["fact_text"])
        fact.needs_review = False  # the owner has read and set it
    if "field" in edits or "value" in edits:
        field = (edits.get("field") or "").strip() or None
        value = (edits.get("value") or "").strip() or None
        if field and field not in clean.IDENTITY_FIELDS:
            raise ApiError(422, "VALIDATION_ERROR", f"Unknown profile field '{field}'.")
        if value and len(value) > clean.MAX_VALUE:
            raise ApiError(422, "VALIDATION_ERROR", "That value is too long.")
        if field and value and not personal.classify(value):
            fact.suggested_section, fact.suggested_field, fact.suggested_value = (
                "identity",
                field,
                value,
            )
        else:
            fact.suggested_section, fact.suggested_field, fact.suggested_value = (
                "learned",
                None,
                None,
            )


def _write_identity(db: Session, bot_id: str, field: str, value: str) -> None:
    data = {k: v for k, v in _identity_dict(db, bot_id).items() if k in IdentityIn.model_fields}
    data[field] = value
    profile.put_identity(db, bot_id, IdentityIn.model_validate(data))
    logs.add(db, bot_id, None, "profile_updated", detail="identity")


def update(db: Session, bot_id: str, fact_id: str, edits: dict) -> LearnedFact:
    """Edit a fact. Field/value (the identity suggestion) only while it is pending."""
    fact = _require(db, bot_id, fact_id)
    if fact.status == "rejected":
        raise ApiError(409, "FACT_REJECTED", "This fact was rejected.")
    if fact.status == "approved":
        edits = {k: v for k, v in edits.items() if k == "fact_text"}
    _apply_edits(fact, {k: v for k, v in edits.items() if k in _EDITABLE})
    fact.updated_at = utcnow()
    db.flush()
    return fact


def approve(
    db: Session,
    bot_id: str,
    fact_id: str,
    *,
    edits: dict | None = None,
    mode: str | None = None,
) -> LearnedFact:
    """Make a pending fact known to the bot. Idempotent: approving twice is a no-op."""
    fact = _require(db, bot_id, fact_id)
    if fact.status == "approved":
        return fact
    if fact.status == "rejected":
        raise ApiError(409, "FACT_REJECTED", "This fact was rejected.")
    if mode is not None and mode not in MODES:
        raise ApiError(422, "VALIDATION_ERROR", "mode must be 'replace' or 'keep_both'.")
    _apply_edits(fact, {k: v for k, v in (edits or {}).items() if k in _EDITABLE})
    if fact.suggested_section == "identity" and fact.suggested_field and fact.suggested_value:
        field, value = fact.suggested_field, fact.suggested_value
        current = current_value(db, bot_id, field)
        if current is not None and current.lower() != value.lower():
            if mode is None:
                raise ApiError(
                    409,
                    "IDENTITY_FIELD_SET",
                    f"{field.replace('_', ' ').capitalize()} is already set. "
                    "Replace it or keep both?",
                    details=[{"field": field, "current": current, "new": value}],
                )
            if mode == "keep_both":
                fact.suggested_section = "learned"  # stays a free-text fact
        if fact.suggested_section == "identity":
            _write_identity(db, bot_id, field, value)
    now = utcnow()
    fact.status = "approved"
    fact.approved_at = now
    fact.needs_review = False
    fact.updated_at = now
    if fact.open_question_id:
        oq = open_questions.get(db, bot_id, fact.open_question_id)
        if oq is not None:
            oq.status = "answered"
            oq.answered_fact_id = fact.id
            oq.updated_at = now
    logs.add(db, bot_id, None, "fact_approved", detail=fact.suggested_section)
    db.flush()
    return fact


def reject(db: Session, bot_id: str, fact_id: str) -> LearnedFact:
    """Reject a pending fact; its open question goes back to the inbox. Idempotent."""
    fact = _require(db, bot_id, fact_id)
    if fact.status == "rejected":
        return fact
    if fact.status == "approved":
        raise ApiError(409, "FACT_APPROVED", "This fact is already approved. Delete it instead.")
    now = utcnow()
    fact.status = "rejected"
    fact.updated_at = now
    if fact.open_question_id:
        oq = open_questions.get(db, bot_id, fact.open_question_id)
        if oq is not None and oq.status in ("answered", "dismissed"):
            oq.status = "open"
            oq.updated_at = now
    db.flush()
    return fact


def delete(db: Session, bot_id: str, fact_id: str) -> None:
    """Soft delete: the bot stops stating it on the next message."""
    fact = _require(db, bot_id, fact_id)
    now = utcnow()
    fact.deleted_at = fact.updated_at = now
    if fact.open_question_id:
        oq = open_questions.get(db, bot_id, fact.open_question_id)
        if oq is not None and oq.answered_fact_id == fact.id and oq.status == "answered":
            oq.status = "open"  # the answer is gone, so the question is open again
            oq.answered_fact_id = None
            oq.updated_at = now
    db.flush()
