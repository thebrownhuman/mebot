"""knowledge_chunks + retrieval_settings access. Every query filters on bot_id."""

import json

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mebot.models import KnowledgeChunk, RetrievalSettings, utcnow
from mebot.retrieval.chunker import Chunk

MODES = ("auto", "always", "off")


# --- settings --------------------------------------------------------------------------


def get_settings(db: Session, bot_id: str) -> RetrievalSettings | None:
    return db.scalar(select(RetrievalSettings).where(RetrievalSettings.bot_id == bot_id))


def get_or_create_settings(db: Session, bot_id: str) -> RetrievalSettings:
    row = get_settings(db, bot_id)
    if row is None:
        try:
            row = RetrievalSettings(bot_id=bot_id)
            db.add(row)
            db.commit()
        except IntegrityError:  # created concurrently
            db.rollback()
            row = get_settings(db, bot_id)
    return row


# --- chunks ----------------------------------------------------------------------------


def rows(db: Session, bot_id: str) -> dict[str, KnowledgeChunk]:
    """The bot's stored chunks by item_key."""
    found = db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.bot_id == bot_id))
    return {r.item_key: r for r in found}


def is_stale(stored: dict[str, KnowledgeChunk], chunks: list[Chunk]) -> bool:
    """True when the stored index differs from what the profile chunks to now."""
    if len(stored) != len(chunks):
        return True
    for c in chunks:
        row = stored.get(c.item_key)
        if row is None or row.content_hash != c.content_hash or row.order_index != c.order:
            return True
    return False


def sync(db: Session, bot_id: str, chunks: list[Chunk]) -> dict[str, int]:
    """Make the stored chunks match ``chunks``. Incremental: an unchanged chunk (same
    content_hash) is left alone, embedding included. The caller commits."""
    stored = rows(db, bot_id)
    added = updated = 0
    now = utcnow()
    for c in chunks:
        row = stored.pop(c.item_key, None)
        if row is None:
            db.add(
                KnowledgeChunk(
                    bot_id=bot_id,
                    section=c.section,
                    item_key=c.item_key,
                    title=c.title,
                    text=c.text,
                    content_hash=c.content_hash,
                    order_index=c.order,
                    updated_at=now,
                )
            )
            added += 1
        elif row.content_hash != c.content_hash:
            row.section, row.title, row.text = c.section, c.title, c.text
            row.content_hash, row.order_index = c.content_hash, c.order
            row.embedding = row.embedding_model = None  # stale vector
            row.updated_at = now
            updated += 1
        elif row.order_index != c.order:
            row.order_index = c.order  # only moved: the vector is still right
    for row in stored.values():  # items no longer in the profile
        db.delete(row)
    db.flush()
    return {"added": added, "updated": updated, "removed": len(stored)}


def clear_embeddings(db: Session, bot_id: str) -> None:
    db.execute(
        KnowledgeChunk.__table__.update()
        .where(KnowledgeChunk.bot_id == bot_id)
        .values(embedding=None, embedding_model=None)
    )


def delete_all(db: Session, bot_id: str) -> None:
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.bot_id == bot_id))


def count(db: Session, bot_id: str) -> int:
    return db.scalar(
        select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.bot_id == bot_id)
    )


def embedded_count(db: Session, bot_id: str, model: str | None) -> int:
    if not model:
        return 0
    return db.scalar(
        select(func.count())
        .select_from(KnowledgeChunk)
        .where(
            KnowledgeChunk.bot_id == bot_id,
            KnowledgeChunk.embedding.is_not(None),
            KnowledgeChunk.embedding_model == model,
        )
    )


def titles(db: Session, bot_id: str, chunk_ids_json: str | None) -> list[dict]:
    """[{id, section, title}] for a message's stored chunk ids, in the stored order. Chunks
    deleted since are skipped."""
    try:
        ids = json.loads(chunk_ids_json or "[]")
    except ValueError:
        return []
    if not isinstance(ids, list) or not ids:
        return []
    found = {
        r.id: r
        for r in db.scalars(
            select(KnowledgeChunk).where(
                KnowledgeChunk.bot_id == bot_id, KnowledgeChunk.id.in_([str(i) for i in ids])
            )
        )
    }
    return [
        {"id": i, "section": found[i].section, "title": found[i].title}
        for i in ids
        if i in found
    ]
