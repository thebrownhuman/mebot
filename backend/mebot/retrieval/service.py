"""knowledge_for(): the one place that decides full profile vs retrieval for a chat turn.

Callers get a ``Knowledge`` and don't care which mode produced it. Small profiles (and
mode ``off``) get ``render_profile`` exactly as before, byte for byte.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from mebot.profile.data import ProfileData
from mebot.profile.render import approx_tokens, render_profile, render_retrieval
from mebot.repos import retrieval as repo
from mebot.retrieval import chunker, search

log = logging.getLogger("mebot.retrieval")

COSINE_FLOOR = 0.25  # below this an embedding match counts as "nothing found"
Embedder = Callable[[list[str], str], Awaitable[list[list[float]]]]


@dataclass
class Knowledge:
    text: str  # goes into build_system_prompt(profile=...)
    retrieval: bool = False
    chunk_ids: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    profile_tokens: int = 0  # the whole profile, for the threshold comparison
    prompt_tokens: int = 0  # what this turn's knowledge block costs
    fallback: bool = False  # nothing matched: showed the latest job + top projects
    hybrid: bool = False  # embeddings contributed to the ranking


def uses_retrieval(mode: str, profile_tokens: int, threshold: int) -> bool:
    if mode == "always":
        return True
    return mode == "auto" and profile_tokens > threshold


async def knowledge_for(
    db: Session,
    bot_id: str,
    profile: ProfileData,
    user_texts: list[str],
    *,
    threshold: int,
    budget: int,
    embedder: Embedder | None = None,
    as_of: date | None = None,
) -> Knowledge:
    """``user_texts``: the current visitor message first, then the previous one (if any)."""
    full = render_profile(profile, as_of)
    tokens = approx_tokens(full)
    settings = repo.get_settings(db, bot_id)
    mode = settings.mode if settings else "auto"
    if not uses_retrieval(mode, tokens, threshold):
        return Knowledge(full, profile_tokens=tokens, prompt_tokens=tokens)

    chunks = chunker.build_chunks(profile)
    stored = repo.rows(db, bot_id)
    if repo.is_stale(stored, chunks):  # a save/import/approve hook hasn't run (yet)
        repo.sync(db, bot_id, chunks)
        db.commit()
        stored = repo.rows(db, bot_id)

    query = search.build_query(
        user_texts[0] if user_texts else "", user_texts[1] if len(user_texts) > 1 else None
    )
    ignore = search.name_terms(profile.identity.get("full_name") or "")
    lexical = search.lexical_rank(chunks, query, ignore)
    semantic = await _semantic(settings, embedder, chunks, stored, query)

    fallback = False
    if lexical or semantic:
        ranked = search.rrf(lexical, semantic) if semantic else lexical
        picked = search.select(chunks, ranked, budget)
    else:
        fallback = True
        latest = search.fallback(profile, chunks)
        picked = search.select(chunks, latest, budget, min_keep=len(latest))

    text = render_retrieval(
        profile, chunker.outline(profile), [chunks[i].text for i in picked], as_of
    )
    return Knowledge(
        text,
        retrieval=True,
        chunk_ids=[stored[chunks[i].item_key].id for i in picked],
        titles=[chunks[i].title for i in picked],
        profile_tokens=tokens,
        prompt_tokens=approx_tokens(text),
        fallback=fallback,
        hybrid=bool(semantic),
    )


async def _semantic(settings, embedder, chunks, stored, query) -> list[int]:
    """Chunk indexes by cosine similarity, or [] (embeddings off, none stored, or failing:
    chat never waits on or breaks because of them)."""
    if not (embedder and settings and settings.embeddings_enabled and settings.embedding_model):
        return []
    model = settings.embedding_model
    vectors = {}
    for i, c in enumerate(chunks):
        row = stored.get(c.item_key)
        if row is not None and row.embedding and row.embedding_model == model:
            vectors[i] = search.unpack(row.embedding)
    if not vectors or not query.strip():
        return []
    try:
        query_vec = (await embedder([query], model))[0]
    except Exception:  # noqa: BLE001 - any failure falls back to lexical
        log.warning("query embedding failed; using lexical ranking", exc_info=False)
        return []
    return [i for i, score in search.cosine_rank(query_vec, vectors) if score >= COSINE_FLOOR]
