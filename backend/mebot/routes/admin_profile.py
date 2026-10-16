"""Owner's structured profile: identity/notes singletons, generic list sections,
and a preview of exactly what the chat prompt will contain.

Concurrent edits of the same item are last-write-wins (no locking)."""

from fastapi import APIRouter, Body, Depends, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from mebot.db import get_db
from mebot.deps import csrf_on_mutation, get_current_admin, get_current_bot, require_setup_done
from mebot.errors import ApiError
from mebot.models import Bot
from mebot.profile import sections
from mebot.profile.data import load_profile
from mebot.profile.facts import compute_facts
from mebot.profile.render import approx_tokens, render_profile
from mebot.profile.schemas import IdentityIn, NotesIn, OrderIn
from mebot.repos import learned_facts, logs
from mebot.repos import profile_items as repo

router = APIRouter(
    prefix="/api/admin/profile",
    dependencies=[
        Depends(require_setup_done),
        Depends(get_current_admin),
        Depends(csrf_on_mutation),
    ],
)


def _section(slug: str) -> sections.Section:
    sec = sections.get_section(slug)
    if sec is None:
        raise ApiError(404, "NOT_FOUND", f"Unknown profile section '{slug}'")
    return sec


def _parse(schema: type[BaseModel], payload) -> BaseModel:
    try:
        return schema.model_validate(payload if isinstance(payload, dict) else {})
    except ValidationError as e:
        # Same 422 shape as FastAPI's own body validation (see main._validation_error).
        raise RequestValidationError(e.errors()) from None


def _not_found() -> ApiError:
    return ApiError(404, "NOT_FOUND", "Item not found")


def _changed(db: Session, bot: Bot, section: str) -> None:
    logs.add(db, bot.id, None, "profile_updated", detail=section)
    db.commit()


# --- singletons (declared before /{section} so they win the match) ---------------------


@router.get("/identity")
def read_identity(db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    row = repo.get_identity(db, bot.id)
    return repo.serialize(None, row) if row else IdentityIn().model_dump()


@router.put("/identity")
def write_identity(
    payload: dict = Body(...), db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)
):
    row = repo.put_identity(db, bot.id, _parse(IdentityIn, payload))
    _changed(db, bot, "identity")
    return repo.serialize(None, row)


@router.get("/notes")
def read_notes(db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    row = repo.get_notes(db, bot.id)
    return {"content": row.content if row else ""}


@router.put("/notes")
def write_notes(
    payload: dict = Body(...), db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)
):
    row = repo.put_notes(db, bot.id, _parse(NotesIn, payload))
    _changed(db, bot, "notes")
    return {"content": row.content}


@router.get("/facts")
def facts(db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    """Server-computed facts (as of today, UTC) that head the chat prompt."""
    return compute_facts(load_profile(db, bot.id))


@router.get("/preview")
def preview(db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    data = load_profile(db, bot.id)
    text = render_profile(data)
    warnings = []
    if len(data.learned) >= learned_facts.MAX_ACTIVE:
        warnings.append(
            f"Only the newest {learned_facts.MAX_ACTIVE} learned facts are used. "
            "Move older ones into profile sections (FAQ, projects) to keep them."
        )
    return {
        "text": text,
        "chars": len(text),
        "approx_tokens": approx_tokens(text),
        "learned_facts": len(data.learned),
        "warnings": warnings,
    }


# --- list sections -----------------------------------------------------------------------


@router.get("/{section}")
def list_section(section: str, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    sec = _section(section)
    return {"items": [repo.serialize(sec, r) for r in repo.list_items(db, sec, bot.id)]}


@router.post("/{section}", status_code=201)
def create_item(
    section: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    sec = _section(section)
    data = _parse(sec.schema, payload)
    if repo.count(db, sec, bot.id) >= sections.MAX_ITEMS:
        raise ApiError(
            422, "LIMIT_REACHED", f"A section can hold at most {sections.MAX_ITEMS} items."
        )
    row = repo.create(db, sec, bot.id, data)
    _changed(db, bot, section)
    return repo.serialize(sec, row)


@router.put("/{section}/order", status_code=204)
def reorder(
    section: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    sec = _section(section)
    order = _parse(OrderIn, payload)
    if not repo.reorder(db, sec, bot.id, order.ids):
        db.rollback()
        msg = "ids must list every item in this section exactly once"
        raise ApiError(422, "VALIDATION_ERROR", msg, details=[{"field": "ids", "message": msg}])
    _changed(db, bot, section)
    return Response(status_code=204)


@router.put("/{section}/{item_id}")
def update_item(
    section: str,
    item_id: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    sec = _section(section)
    data = _parse(sec.schema, payload)
    row = repo.get(db, sec, bot.id, item_id)
    if row is None:
        raise _not_found()
    repo.update(db, sec, row, data)
    _changed(db, bot, section)
    return repo.serialize(sec, row)


@router.delete("/{section}/{item_id}", status_code=204)
def delete_item(
    section: str, item_id: str, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)
):
    sec = _section(section)
    row = repo.get(db, sec, bot.id, item_id)
    if row is None:
        raise _not_found()
    repo.soft_delete(db, row)
    _changed(db, bot, section)
    return Response(status_code=204)
