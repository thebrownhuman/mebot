"""Owner's structured profile: identity/notes singletons, generic list sections,
and a preview of exactly what the chat prompt will contain.

Concurrent edits of the same item are last-write-wins (no locking)."""

from fastapi import APIRouter, Body, Depends, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from mebot import channels
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
from mebot.retrieval.hooks import Reindexer, get_reindexer

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


def _confirm_phone_share(data: BaseModel, was_shared: bool) -> None:
    """Sharing a phone number takes an explicit yes (only when turning sharing on)."""
    if getattr(data, "kind", None) == "phone" and data.share and not was_shared:
        if not data.confirm_share_phone:
            raise ApiError(
                422,
                "CONFIRM_REQUIRED",
                "Confirm you want to share your phone number with recruiters.",
            )


def _changed(db: Session, bot: Bot, section: str, reindex: Reindexer) -> None:
    logs.add(db, bot.id, None, "profile_updated", detail=section)
    db.commit()
    reindex(bot.id, section)  # background: keeps the retrieval index in step


# --- singletons (declared before /{section} so they win the match) ---------------------


@router.get("/identity")
def read_identity(db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    row = repo.get_identity(db, bot.id)
    return repo.serialize(None, row) if row else IdentityIn().model_dump()


@router.put("/identity")
def write_identity(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    reindex: Reindexer = Depends(get_reindexer),
):
    row = repo.put_identity(db, bot.id, _parse(IdentityIn, payload))
    _changed(db, bot, "identity", reindex)
    return repo.serialize(None, row)


@router.get("/notes")
def read_notes(db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    row = repo.get_notes(db, bot.id)
    return {"content": row.content if row else ""}


@router.put("/notes")
def write_notes(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    reindex: Reindexer = Depends(get_reindexer),
):
    row = repo.put_notes(db, bot.id, _parse(NotesIn, payload))
    _changed(db, bot, "notes", reindex)
    return {"content": row.content}


@router.get("/facts")
def facts(db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    """Server-computed facts (as of today, UTC) that head the chat prompt."""
    return compute_facts(load_profile(db, bot.id))


def _phone_warnings(data) -> list[str]:
    """The output guard hides phone-shaped strings, but free text is the wrong place for one."""
    shared = {
        channels.digits(c["value"])
        for c in data.items("links")
        if c.get("kind") == "phone" and c.get("share")
    }
    where = {
        "notes": data.notes,
        "FAQ": " ".join(f["question"] + " " + f["answer"] for f in data.items("faqs")),
        "learned facts": " ".join(data.learned),
    }
    return [
        f"A phone number appears in your {name}. The bot will never show it; "
        "add it as a Phone channel above and remove it from the text."
        for name, text in where.items()
        if any(d not in shared for d in channels.phone_numbers(text))
    ]


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
    warnings += _phone_warnings(data)
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
    reindex: Reindexer = Depends(get_reindexer),
):
    sec = _section(section)
    data = _parse(sec.schema, payload)
    if repo.count(db, sec, bot.id) >= sec.limit:
        raise ApiError(422, "LIMIT_REACHED", f"A section can hold at most {sec.limit} items.")
    _confirm_phone_share(data, was_shared=False)
    row = repo.create(db, sec, bot.id, data)
    _changed(db, bot, section, reindex)
    return repo.serialize(sec, row)


@router.put("/{section}/order", status_code=204)
def reorder(
    section: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    reindex: Reindexer = Depends(get_reindexer),
):
    sec = _section(section)
    order = _parse(OrderIn, payload)
    if not repo.reorder(db, sec, bot.id, order.ids):
        db.rollback()
        msg = "ids must list every item in this section exactly once"
        raise ApiError(422, "VALIDATION_ERROR", msg, details=[{"field": "ids", "message": msg}])
    _changed(db, bot, section, reindex)
    return Response(status_code=204)


@router.put("/{section}/{item_id}")
def update_item(
    section: str,
    item_id: str,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    reindex: Reindexer = Depends(get_reindexer),
):
    sec = _section(section)
    row = repo.get(db, sec, bot.id, item_id)
    if row is None:
        raise _not_found()
    if section == "links":
        # Partial update (e.g. just the Share switch): unsent fields keep their value.
        keep = {k: getattr(row, k) for k in ("kind", "label", "value", "share")}
        payload = {**keep, **payload}
    data = _parse(sec.schema, payload)
    _confirm_phone_share(data, was_shared=bool(getattr(row, "share", False)))
    repo.update(db, sec, row, data)
    _changed(db, bot, section, reindex)
    return repo.serialize(sec, row)


@router.delete("/{section}/{item_id}", status_code=204)
def delete_item(
    section: str,
    item_id: str,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    reindex: Reindexer = Depends(get_reindexer),
):
    sec = _section(section)
    row = repo.get(db, sec, bot.id, item_id)
    if row is None:
        raise _not_found()
    repo.soft_delete(db, row)
    _changed(db, bot, section, reindex)
    return Response(status_code=204)
