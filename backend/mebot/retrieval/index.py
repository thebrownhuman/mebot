"""Reindexing: keep knowledge_chunks in step with the profile, and (optionally) embed them.

Runs as a background task after profile save / import apply / learned-fact approve and on
"Rebuild index"; chat also re-syncs lazily if it finds the index stale. Never in the
request path of a visitor: embedding calls go through the owner's key and token cap.
"""

import logging

from sqlalchemy.orm import Session

from mebot.limits import counters
from mebot.llm import service as llm
from mebot.llm.base import LLMError
from mebot.models import utcnow
from mebot.profile.data import load_profile
from mebot.profile.render import approx_tokens, render_profile
from mebot.repos import limits as limits_repo
from mebot.repos import retrieval as repo
from mebot.retrieval import chunker, search
from mebot.retrieval.service import uses_retrieval

log = logging.getLogger("mebot.retrieval")

EMBED_BATCH = 64
MAX_ERROR = 300


def sync_chunks(db: Session, bot_id: str, *, force: bool = False) -> dict[str, int]:
    """Re-chunk the profile and update the stored chunks (cheap, no network). Commits."""
    profile = load_profile(db, bot_id)
    if force:
        repo.clear_embeddings(db, bot_id)
    result = repo.sync(db, bot_id, chunker.build_chunks(profile))
    settings = repo.get_or_create_settings(db, bot_id)
    settings.last_indexed_at = utcnow()
    db.commit()
    return result


def _token_cap_reached(db: Session, bot_id: str, limiter) -> bool:
    cap = limits_repo.get_or_create(db, bot_id).daily_token_cap
    if cap is None:
        return False
    row = counters.get(db, bot_id, "bot_day", "*", limiter.today())
    return row is not None and row.tokens >= cap


async def reindex(
    session_factory, bot_id: str, secret_key: str, limiter, *, threshold: int, force: bool = False
) -> None:
    """Background entry point. Never raises: a failure is stored for the Knowledge panel."""
    try:
        with session_factory() as db:
            sync_chunks(db, bot_id, force=force)
            await embed_pending(db, bot_id, secret_key, limiter, threshold=threshold)
    except Exception:  # noqa: BLE001 - background task
        log.exception("reindex failed for bot %s", bot_id)


async def embed_pending(
    db: Session, bot_id: str, secret_key: str, limiter, *, threshold: int
) -> None:
    settings = repo.get_or_create_settings(db, bot_id)
    if not (settings.embeddings_enabled and settings.embedding_model):
        return
    profile = load_profile(db, bot_id)
    # No point paying for vectors a small profile will never use.
    if not uses_retrieval(settings.mode, approx_tokens(render_profile(profile)), threshold):
        return
    model = settings.embedding_model
    todo = [
        r for r in repo.rows(db, bot_id).values() if not r.embedding or r.embedding_model != model
    ]
    if not todo:
        settings.last_error = None
        db.commit()
        return
    status, _, cfg = llm.load(db, bot_id, secret_key)
    if cfg is None:
        settings.last_error = "AI provider is not configured."
        db.commit()
        return
    client = cfg.client()
    error: str | None = None
    for start in range(0, len(todo), EMBED_BATCH):
        if _token_cap_reached(db, bot_id, limiter):
            error = "Daily token cap reached; embeddings will finish after the cap resets."
            break
        batch = todo[start : start + EMBED_BATCH]
        try:
            vectors = await client.embed([r.text for r in batch], model=model)
        except LLMError as e:
            error = e.message[:MAX_ERROR]
            break
        except Exception as e:  # noqa: BLE001
            error = f"Embedding failed ({type(e).__name__})."
            break
        for row, vec in zip(batch, vectors, strict=True):
            row.embedding, row.embedding_model = search.pack(vec), model
        reported = getattr(client, "embed_tokens", None)
        estimated = reported is None
        spent = reported if reported else sum(approx_tokens(r.text) for r in batch)
        counters.add_tokens(
            db,
            bot_id,
            [("bot_day", "*")],
            limiter.today(),
            spent,
            estimated=estimated,
            now=limiter.wall(),
        )
        db.commit()
    settings.last_error = error
    db.commit()
    if error:
        log.warning("embedding stopped: %s", error)
