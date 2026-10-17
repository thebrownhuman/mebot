"""Ranking and selection. Lexical (SQLite FTS5 BM25) always works, offline; embeddings are
an optional second ranking fused in with reciprocal-rank fusion.

The FTS index is built in memory per query: profiles are hundreds of chunks, so it costs
milliseconds and there is no index to keep in sync with the stored chunks.
"""

import math
import re
import sqlite3
import struct
from collections.abc import Sequence

from mebot.profile.data import ProfileData
from mebot.retrieval.chunker import Chunk

RRF_K = 60
FALLBACK_PROJECTS = 3
TITLE_WEIGHT = 3.0
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = frozenset(
    """a about an and any are as at be been but by can could did do does for from had has have he
    her his how i if in into is it its me my of on or our she so than that the their them then
    there these they this to us was we were what when where which who why will with would you
    your tell more also please hi hello hey thanks""".split()
)


def build_query(current: str, previous: str | None) -> str:
    """Current visitor message plus the one before it, for follow-ups like 'what stack?'."""
    return f"{current} {previous}".strip() if previous else current.strip()


def _terms(query: str, ignore: frozenset[str]) -> list[str]:
    seen: dict[str, None] = {}
    for w in _WORD.findall(query[:2000].lower()):
        if (len(w) > 1 or w.isdigit()) and w not in _STOP and w not in ignore:
            seen[w] = None
    return list(seen)[:40]


def name_terms(full_name: str) -> frozenset[str]:
    """The owner's own name words: in nearly every chunk, so useless for ranking."""
    return frozenset(w.lower() for w in _WORD.findall(full_name))


def lexical_rank(
    chunks: Sequence[Chunk], query: str, ignore: frozenset[str] = frozenset()
) -> list[int]:
    """Indexes of the chunks matching the query, best BM25 match first."""
    terms = _terms(query, ignore)
    if not terms or not chunks:
        return []
    match = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
    con = sqlite3.connect(":memory:")
    try:
        con.execute(
            "create virtual table c using fts5(title, body, "
            "tokenize='porter unicode61 remove_diacritics 2')"
        )
        con.executemany(
            "insert into c(rowid, title, body) values (?, ?, ?)",
            [(i, c.title, c.text) for i, c in enumerate(chunks)],
        )
        rows = con.execute(
            "select rowid from c where c match ? order by bm25(c, ?, 1.0), rowid",
            (match, TITLE_WEIGHT),
        ).fetchall()
    except sqlite3.OperationalError:
        return []  # a query FTS5 cannot parse: behave like "no match", never break chat
    finally:
        con.close()
    return [r[0] for r in rows]


def pack(vec: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def cosine_rank(
    query: Sequence[float], vectors: dict[int, Sequence[float]]
) -> list[tuple[int, float]]:
    """(index, cosine) best first; vectors of another dimension are skipped."""
    qn = math.sqrt(sum(x * x for x in query))
    if qn == 0:
        return []
    scored = []
    for i, v in vectors.items():
        if len(v) != len(query):
            continue
        vn = math.sqrt(sum(x * x for x in v))
        if vn:
            scored.append((i, sum(a * b for a, b in zip(query, v, strict=True)) / (qn * vn)))
    return sorted(scored, key=lambda t: (-t[1], t[0]))


def rrf(*rankings: Sequence[int]) -> list[int]:
    """Reciprocal-rank fusion of several best-first lists of indexes."""
    score: dict[int, float] = {}
    for ranking in rankings:
        for pos, i in enumerate(ranking):
            score[i] = score.get(i, 0.0) + 1.0 / (RRF_K + pos + 1)
    return sorted(score, key=lambda i: (-score[i], i))


def select(
    chunks: Sequence[Chunk], ranked: Sequence[int], budget_tokens: int, min_keep: int = 3
) -> list[int]:
    """Fill best-first until the budget; always keep the top ``min_keep``. Returned in
    profile order (stable, more readable) rather than score order."""
    picked: list[int] = []
    used = 0
    for i in ranked:
        cost = chunks[i].tokens
        if len(picked) < min_keep or used + cost <= budget_tokens:
            picked.append(i)
            used += cost
    return sorted(picked, key=lambda i: chunks[i].order)


def _recency(e: dict) -> tuple[str, str]:
    return (e.get("end_month") or "9999-99", e.get("start_month") or "")


def fallback(profile: ProfileData, chunks: Sequence[Chunk]) -> list[int]:
    """Nothing matched: the most recent job plus the first projects, so the model can answer
    or flag UNANSWERED correctly instead of seeing nothing."""
    by_key = {c.item_key: i for i, c in enumerate(chunks)}
    out: list[int] = []
    jobs = [
        (e, f"experiences:{e.get('id') or n}") for n, e in enumerate(profile.items("experiences"))
    ]
    if jobs:
        _, key = max(jobs, key=lambda t: _recency(t[0]))
        if key in by_key:
            out.append(by_key[key])
    for n, pr in enumerate(profile.items("projects")[:FALLBACK_PROJECTS]):
        key = f"projects:{pr.get('id') or n}"
        if key in by_key:
            out.append(by_key[key])
    return out
