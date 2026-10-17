"""Owner-only learning loop: the open-questions inbox and the learned-facts memory.

The AI only ever *proposes*: answering a question or adding a fact creates a pending
learned fact; nothing reaches the chat until the owner approves it.
"""

from datetime import UTC

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from mebot import persona
from mebot.db import get_db
from mebot.deps import csrf_on_mutation, get_current_admin, get_current_bot, require_setup_done
from mebot.errors import ApiError
from mebot.learning import service as learning
from mebot.models import Bot, OpenQuestion
from mebot.profile.schemas import AvoidTopicIn
from mebot.profile.sections import SECTIONS
from mebot.repos import learned_facts, logs, open_questions
from mebot.repos import profile_items as profile
from mebot.retrieval.hooks import Reindexer, get_reindexer

router = APIRouter(
    prefix="/api/admin",
    dependencies=[
        Depends(require_setup_done),
        Depends(get_current_admin),
        Depends(csrf_on_mutation),
    ],
)

MAX_ANSWER = 2000


def _iso(dt) -> str | None:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def _question(q: OpenQuestion) -> dict:
    return {
        "id": q.id,
        "question": q.question,
        "ask_count": q.ask_count,
        "first_asked_at": _iso(q.first_asked_at),
        "last_asked_at": _iso(q.last_asked_at),
        "status": q.status,
        "answered_fact_id": q.answered_fact_id,
    }


def _get_question(db: Session, bot: Bot, qid: str) -> OpenQuestion:
    q = open_questions.get(db, bot.id, qid)
    if q is None:
        raise ApiError(404, "NOT_FOUND", "Question not found")
    return q


class AnswerIn(BaseModel):
    answer: str = Field(max_length=MAX_ANSWER)

    @field_validator("answer")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("write an answer first")
        return v.strip()


class NewFactIn(BaseModel):
    text: str = Field(max_length=MAX_ANSWER)
    question: str | None = Field(default=None, max_length=open_questions.MAX_QUESTION)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("write the fact first")
        return v.strip()


class FactEditIn(BaseModel):
    """Only the keys the client sends are applied (null clears the identity suggestion)."""

    model_config = ConfigDict(extra="ignore")
    fact_text: str | None = Field(default=None, max_length=1000)
    field: str | None = Field(default=None, max_length=60)
    value: str | None = Field(default=None, max_length=1000)

    def edits(self) -> dict:
        return {k: getattr(self, k) for k in self.model_fields_set}


class ApproveIn(FactEditIn):
    mode: str | None = Field(default=None, max_length=20)

    def edits(self) -> dict:
        return {k: v for k, v in super().edits().items() if k != "mode"}


# --- open questions -------------------------------------------------------------------


@router.get("/open-questions")
def list_open_questions(
    status: str = "open",
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    if status != "all" and status not in open_questions.STATUSES:
        raise ApiError(422, "VALIDATION_ERROR", "Unknown status.")
    rows = open_questions.list_(db, bot.id, None if status == "all" else status)
    return {
        "items": [_question(q) for q in rows],
        "open_count": open_questions.count_open(db, bot.id),
    }


@router.post("/open-questions/{qid}/answer", status_code=201)
async def answer_question(
    qid: str,
    body: AnswerIn,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    q = _get_question(db, bot, qid)
    fact = await learning.propose(
        db,
        bot.id,
        request.app.state.secret_key,
        question=q.question,
        answer=body.answer,
        source="admin",
        open_question_id=q.id,
    )
    db.commit()
    return learning.serialize(db, fact)


@router.post("/open-questions/{qid}/dismiss")
def dismiss_question(qid: str, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    q = _get_question(db, bot, qid)
    open_questions.set_status(db, q, "dismissed")
    db.commit()
    return _question(q)


@router.post("/open-questions/{qid}/never")
def never_answer(qid: str, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    """Stop the bot discussing this: dismiss it and add an avoid-topic with a polite reply."""
    q = _get_question(db, bot, qid)
    if q.status != "never":
        name = persona.display_name(
            profile.serialize(None, profile.get_identity(db, bot.id))
            if profile.get_identity(db, bot.id)
            else {},
            bot.name,
        )
        sec = SECTIONS["avoid-topics"]
        profile.create(
            db,
            sec,
            bot.id,
            AvoidTopicIn(
                topic=q.question[:200],
                reply=f"That's not something I can discuss. Happy to help with {name}'s "
                "work and experience.",
            ),
        )
        logs.add(db, bot.id, None, "profile_updated", detail="avoid-topics")
        open_questions.set_status(db, q, "never")
    db.commit()
    return _question(q)


# --- learned facts --------------------------------------------------------------------


@router.get("/learned-facts")
def list_learned_facts(
    status: str | None = None,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    if status is not None and status not in learned_facts.STATUSES:
        raise ApiError(422, "VALIDATION_ERROR", "Unknown status.")
    rows = learned_facts.list_(db, bot.id, status)
    return {
        "items": [learning.serialize(db, f) for f in rows],
        "active_count": learned_facts.count_active_learned(db, bot.id),
        "max_active": learned_facts.MAX_ACTIVE,
    }


@router.post("/learned-facts", status_code=201)
async def add_fact(
    body: NewFactIn,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    """The owner states a fact directly; it is cleaned and waits for approval too."""
    fact = await learning.propose(
        db,
        bot.id,
        request.app.state.secret_key,
        question=body.question or "Added by the owner",
        answer=body.text,
        source="admin",
    )
    db.commit()
    return learning.serialize(db, fact)


@router.post("/learned-facts/{fid}/approve")
def approve_fact(
    fid: str,
    body: ApproveIn | None = None,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    reindex: Reindexer = Depends(get_reindexer),
):
    body = body or ApproveIn()
    fact = learning.approve(db, bot.id, fid, edits=body.edits(), mode=body.mode)
    db.commit()
    reindex(bot.id)
    return learning.serialize(db, fact)


@router.post("/learned-facts/{fid}/reject")
def reject_fact(fid: str, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    fact = learning.reject(db, bot.id, fid)
    db.commit()
    return learning.serialize(db, fact)


@router.put("/learned-facts/{fid}")
def edit_fact(
    fid: str,
    body: FactEditIn,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    reindex: Reindexer = Depends(get_reindexer),
):
    fact = learning.update(db, bot.id, fid, body.edits())
    db.commit()
    reindex(bot.id)
    return learning.serialize(db, fact)


@router.delete("/learned-facts/{fid}", status_code=204)
def delete_fact(
    fid: str,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    reindex: Reindexer = Depends(get_reindexer),
):
    learning.delete(db, bot.id, fid)
    db.commit()
    reindex(bot.id)
    return Response(status_code=204)
