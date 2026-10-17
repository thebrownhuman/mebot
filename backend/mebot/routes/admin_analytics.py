"""Dashboard numbers and the owner's data settings (timezone, retention)."""

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from mebot import retention
from mebot.analytics import cache, service
from mebot.db import get_db
from mebot.deps import csrf_on_mutation, get_current_admin, get_current_bot, require_setup_done
from mebot.errors import ApiError
from mebot.models import Bot
from mebot.repos import logs

router = APIRouter(
    prefix="/api/admin",
    dependencies=[
        Depends(require_setup_done),
        Depends(get_current_admin),
        Depends(csrf_on_mutation),
    ],
)

RETENTION_CHOICES = (30, 90, 180, 365)


@router.get("/analytics/overview")
def overview(
    range: Literal["7d", "30d", "90d"] = Query("7d"),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    return service.cached_overview(db, bot, range)


def _account(db: Session, bot: Bot, preview_days: int | None, previewing: bool) -> dict:
    body = {
        "timezone": bot.timezone,
        "retention_days": bot.retention_days,
        "retention_choices": list(RETENTION_CHOICES),
    }
    if previewing:
        body["will_delete"] = retention.preview(db, bot.id, preview_days)
    return body


@router.get("/account")
def get_account(
    preview_days: int | None = Query(None, ge=1, le=3650),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    """Settings, plus ``will_delete`` (conversations a window of ``preview_days`` would
    remove right now) when ``preview_days`` is given."""
    return _account(db, bot, preview_days, preview_days is not None)


class AccountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(default=None, max_length=64)
    retention_days: int | None = None  # null = keep forever

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("unknown IANA timezone (e.g. Europe/Berlin)") from None
        return v

    @field_validator("retention_days")
    @classmethod
    def _days(cls, v: int | None) -> int | None:
        if v is not None and v not in RETENTION_CHOICES:
            raise ValueError("choose 30, 90, 180, 365 or null (keep forever)")
        return v


@router.put("/account")
def put_account(req: AccountIn, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    sent = req.model_fields_set
    changed = []
    if "timezone" in sent and req.timezone is not None:
        if req.timezone != bot.timezone:
            bot.timezone = req.timezone
            cache.invalidate(bot.id)
        changed.append("timezone")
    if "retention_days" in sent:
        bot.retention_days = req.retention_days
        changed.append("retention_days")
    if changed:
        logs.add(db, bot.id, None, "account_updated", detail=",".join(changed))
    db.commit()
    return _account(db, bot, None, False)


class DeleteAllIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: str = Field(max_length=20)


@router.post("/account/delete-conversations")
def delete_conversations(
    req: DeleteAllIn, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)
):
    if req.confirm != "DELETE":
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "Invalid request",
            [{"field": "confirm", "message": 'type "DELETE" to confirm'}],
        )
    deleted = retention.delete_all(db, bot.id)
    db.commit()
    cache.invalidate(bot.id)
    return {"deleted_sessions": deleted}
