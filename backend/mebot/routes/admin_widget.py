"""Owner-only widget settings and copy-paste snippets. Setup, session and CSRF on writes."""

import re
from html import escape
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from mebot import persona
from mebot.db import get_db
from mebot.deps import csrf_on_mutation, get_current_admin, get_current_bot, require_setup_done
from mebot.errors import ApiError
from mebot.models import Bot, WidgetSettings
from mebot.profile.data import load_profile
from mebot.repos import logs
from mebot.repos import widget as widget_repo
from mebot.widget.origins import MAX_ORIGINS, OriginError, normalise

router = APIRouter(
    prefix="/api/admin",
    dependencies=[
        Depends(require_setup_done),
        Depends(get_current_admin),
        Depends(csrf_on_mutation),
    ],
)

MAX_QUESTIONS = 6
MAX_QUESTION_CHARS = 80
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_AVATAR = re.compile(r"^(https://|http://(localhost|127\.0\.0\.1)(:\d+)?/)\S+$", re.IGNORECASE)


def _origin(v: str) -> str:
    try:
        return normalise(v)
    except OriginError as e:
        raise ValueError(str(e)) from None


def _question(v: str) -> str:
    v = " ".join(v.split())
    if not v:
        raise ValueError("must not be empty")
    if len(v) > MAX_QUESTION_CHARS:
        raise ValueError(f"max {MAX_QUESTION_CHARS} characters")
    return v


def _text(v: str | None) -> str | None:
    return (v or "").strip() or None


class WidgetIn(BaseModel):
    """Partial update: only the fields sent are changed."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = None
    allowed_origins: list[Annotated[str, AfterValidator(_origin)]] = Field(
        default=None, max_length=MAX_ORIGINS
    )
    allow_any_origin: bool = None
    confirm_any_origin: bool = False
    primary_color: str = None
    theme: Literal["light", "dark", "auto"] = None
    position: Literal["right", "left"] = None
    title: Annotated[str | None, AfterValidator(_text)] = Field(default=None, max_length=60)
    avatar_url: Annotated[str | None, AfterValidator(_text)] = Field(default=None, max_length=500)
    launcher_label: Annotated[str | None, AfterValidator(_text)] = Field(
        default=None, max_length=40
    )
    suggested_questions: list[Annotated[str, AfterValidator(_question)]] = Field(
        default=None, max_length=MAX_QUESTIONS
    )
    show_orb: bool = None
    auto_open_seconds: int | None = Field(default=None, ge=5, le=120)

    @field_validator("primary_color")
    @classmethod
    def _color(cls, v: str) -> str:
        if not _HEX.match(v or ""):
            raise ValueError("use a hex colour like #0f766e")
        return v.lower()

    @field_validator("avatar_url")
    @classmethod
    def _avatar(cls, v: str | None) -> str | None:
        if v is not None and not _AVATAR.match(v.strip()):
            raise ValueError("use an https:// image URL")
        return v

    @field_validator("allowed_origins")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))


def _ref(bot: Bot, request: Request) -> str:
    from mebot.routes.widget import embed_ref

    return embed_ref(bot, request.app.state.settings.hosted)


def _out(row: WidgetSettings, bot: Bot, request: Request) -> dict:
    allowed = widget_repo.origins(row)
    return {
        "slug": bot.slug,
        "embed_ref": _ref(bot, request),
        "enabled": row.enabled,
        "allowed_origins": allowed,
        "allow_any_origin": row.allow_any_origin,
        "primary_color": row.primary_color,
        "theme": row.theme,
        "position": row.position,
        "title": row.title,
        "avatar_url": row.avatar_url,
        "launcher_label": row.launcher_label,
        "suggested_questions": widget_repo.questions(row),
        "show_orb": row.show_orb,
        "auto_open_seconds": row.auto_open_seconds,
        # The dashboard hint: on, but only frameable by this install's own origin.
        "needs_origins": row.enabled and not row.allow_any_origin and not allowed,
    }


@router.get("/widget")
def get_widget(
    request: Request, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)
):
    return _out(widget_repo.get_or_create(db, bot.id), bot, request)


@router.put("/widget")
def put_widget(
    req: WidgetIn,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    values = req.model_dump(exclude_unset=True)
    confirm = values.pop("confirm_any_origin", False)
    row = widget_repo.get_or_create(db, bot.id)
    turning_on = values.get("allow_any_origin") is True and not row.allow_any_origin
    if turning_on and not confirm:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "Invalid request",
            [
                {
                    "field": "confirm_any_origin",
                    "message": "any site could embed the chat and use your API key; confirm",
                }
            ],
        )
    for k in ("enabled", "allow_any_origin", "show_orb", "primary_color", "theme", "position"):
        if k in values and values[k] is None:  # not nullable: "null" means leave as is
            values.pop(k)
    for k in ("allowed_origins", "suggested_questions"):
        if k in values and values[k] is None:
            values[k] = []
    widget_repo.update(db, row, values)
    if turning_on:
        logs.add(db, bot.id, None, "WIDGET_ANY_ORIGIN_ON")
    logs.add(db, bot.id, None, "widget_updated", detail=",".join(sorted(values)))
    db.commit()
    return _out(row, bot, request)


def base_url(request: Request) -> str:
    return (request.app.state.settings.public_url or str(request.base_url)).rstrip("/")


@router.get("/widget/snippets")
def snippets(request: Request, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    base = escape(base_url(request))
    slug = escape(_ref(bot, request))
    first = escape(persona.display_name(load_profile(db, bot.id).identity, bot.name))
    loader = f'<script src="{base}/widget/v1.js" data-bot="{slug}"'
    return {
        "script": f"{loader} async></script>",
        "inline": (
            '<div id="mebot-chat"></div>\n'
            f'{loader} data-mode="inline" data-target="#mebot-chat" async></script>'
        ),
        "iframe": (
            f'<iframe src="{base}/embed/{slug}?mode=inline" title="Chat with {first}\'s assistant"'
            ' style="width:100%;height:600px;border:0" loading="lazy"></iframe>'
        ),
    }
