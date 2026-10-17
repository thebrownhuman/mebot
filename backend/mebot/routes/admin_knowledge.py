"""Admin -> Knowledge: how the bot sees a large profile (full vs retrieval), the index, and
the optional embeddings."""

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mebot.db import get_db
from mebot.deps import csrf_on_mutation, get_current_admin, get_current_bot, require_setup_done
from mebot.errors import ApiError
from mebot.llm.providers import get_provider
from mebot.models import AccessLog, Bot, utcnow
from mebot.profile.data import load_profile
from mebot.profile.render import approx_tokens, render_profile
from mebot.repos import llm_configs
from mebot.repos import retrieval as repo
from mebot.retrieval import chunker, index
from mebot.retrieval.hooks import Reindexer, get_reindexer
from mebot.retrieval.service import uses_retrieval

router = APIRouter(
    prefix="/api/admin/knowledge",
    dependencies=[
        Depends(require_setup_done),
        Depends(get_current_admin),
        Depends(csrf_on_mutation),
    ],
)


class KnowledgeIn(BaseModel):
    mode: Literal["auto", "always", "off"] | None = None
    embeddings_enabled: bool | None = None
    embedding_model: str | None = Field(default=None, max_length=200)

    @field_validator("embedding_model")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


def _reason(mode: str, tokens: int, threshold: int) -> str:
    if mode == "always":
        return "Retrieval is forced on, so only the parts relevant to each question are sent."
    if mode == "off":
        return "Retrieval is forced off, so the whole profile is sent with every message."
    if tokens > threshold:
        return (
            f"Your profile is about {tokens:,} tokens, above the {threshold:,}-token threshold, "
            "so only the parts relevant to each question are sent."
        )
    return (
        f"Your profile is about {tokens:,} tokens, within the {threshold:,}-token threshold, "
        "so the whole profile is sent with every message."
    )


def _embedding_support(db: Session, bot_id: str) -> tuple[bool, str | None, str | None]:
    """(supported, why-not, provider's default embedding model)."""
    row = llm_configs.get(db, bot_id)
    provider = get_provider(row.provider) if row else None
    if provider is None:
        return False, "Set up your AI provider first (Admin -> AI Provider).", None
    if not provider.embeddings:
        return (
            False,
            f"{provider.name} has no embeddings API, so ranking stays keyword-based. "
            "That works well for most profiles.",
            None,
        )
    return True, None, provider.default_embedding_model


def _status(db: Session, bot: Bot, request: Request) -> dict:
    settings = request.app.state.settings
    profile = load_profile(db, bot.id)
    tokens = approx_tokens(render_profile(profile))
    row = repo.get_settings(db, bot.id)
    mode = row.mode if row else "auto"
    active = uses_retrieval(mode, tokens, settings.retrieval_threshold_tokens)
    supported, why_not, default_model = _embedding_support(db, bot.id)
    model = row.embedding_model if row else None
    stored = repo.rows(db, bot.id)
    return {
        "mode": mode,
        "effective": "retrieval" if active else "full",
        "reason": _reason(mode, tokens, settings.retrieval_threshold_tokens),
        "profile_tokens": tokens,
        "threshold_tokens": settings.retrieval_threshold_tokens,
        "budget_tokens": settings.retrieval_budget_tokens,
        "chunk_count": len(stored),
        "last_indexed_at": _iso(row.last_indexed_at) if row else None,
        "usage": _usage(db, bot.id),
        "index_stale": repo.is_stale(stored, chunker.build_chunks(profile)),
        "embeddings": {
            "supported": supported,
            "reason": why_not,
            "enabled": bool(row and row.embeddings_enabled),
            "model": model,
            "default_model": default_model,
            "embedded": repo.embedded_count(db, bot.id, model),
            "total": len(stored),
            "last_error": row.last_error if row else None,
        },
    }


USAGE_DAYS = 7


def _usage(db: Session, bot_id: str) -> dict:
    """Last week's retrieval turns: how many, and what they cost vs sending the whole profile."""
    since = utcnow() - timedelta(days=USAGE_DAYS)
    rows = db.scalars(
        select(AccessLog.detail).where(
            AccessLog.bot_id == bot_id,
            AccessLog.event == "RETRIEVAL",
            AccessLog.created_at >= since,
        )
    ).all()
    pairs = []
    for detail in rows:
        try:
            used, whole = (int(x) for x in (detail or "").split("/"))
        except ValueError:
            continue
        pairs.append((used, whole))
    questions = db.scalar(
        select(func.count())
        .select_from(AccessLog)
        .where(
            AccessLog.bot_id == bot_id, AccessLog.event == "question", AccessLog.created_at >= since
        )
    )
    n = len(pairs)
    used = round(sum(u for u, _ in pairs) / n) if n else 0
    whole = round(sum(w for _, w in pairs) / n) if n else 0
    return {
        "days": USAGE_DAYS,
        "questions": questions,
        "retrieval_replies": n,
        "avg_prompt_tokens": used,
        "avg_profile_tokens": whole,
        "saved_percent": round(100 * (1 - used / whole)) if whole else 0,
    }


def _iso(dt) -> str | None:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


@router.get("")
def read(request: Request, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    return _status(db, bot, request)


@router.put("")
def update(
    body: KnowledgeIn,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    reindex: Reindexer = Depends(get_reindexer),
):
    row = repo.get_or_create_settings(db, bot.id)
    changed_embeddings = False
    if body.mode is not None:
        changed_embeddings = changed_embeddings or body.mode != row.mode
        row.mode = body.mode
    wants = row.embeddings_enabled if body.embeddings_enabled is None else body.embeddings_enabled
    if wants:
        supported, why_not, default_model = _embedding_support(db, bot.id)
        if not supported:
            db.rollback()
            raise ApiError(
                422,
                "EMBEDDINGS_UNSUPPORTED",
                why_not or "Embeddings are not available.",
                details=[{"field": "embeddings_enabled", "message": why_not or "unsupported"}],
            )
        model = body.embedding_model or row.embedding_model or default_model
        if not model:
            db.rollback()
            msg = "Enter the embedding model your provider offers."
            raise ApiError(
                422, "VALIDATION_ERROR", msg, details=[{"field": "embedding_model", "message": msg}]
            )
        changed_embeddings = (
            changed_embeddings or not row.embeddings_enabled or model != (row.embedding_model)
        )
        row.embedding_model = model
    elif body.embedding_model is not None:
        row.embedding_model = body.embedding_model
    row.embeddings_enabled = bool(wants)
    db.commit()
    if changed_embeddings and row.embeddings_enabled:
        reindex(bot.id)
    return _status(db, bot, request)


@router.post("/rebuild")
def rebuild(
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    reindex: Reindexer = Depends(get_reindexer),
):
    """Re-chunk the profile now and recompute every embedding (in the background)."""
    index.sync_chunks(db, bot.id, force=True)
    reindex(bot.id)
    return _status(db, bot, request)
