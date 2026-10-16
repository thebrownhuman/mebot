"""Open questions: unanswered professional questions, grouped by wording.

Grouping is deterministic (no LLM call): two questions are the same group when their
normalised token sets have Jaccard similarity >= 0.6, or the normalised text is equal.
"""

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mebot.models import OpenQuestion, utcnow

SIMILARITY = 0.6
NOTIFY_EVERY = timedelta(hours=24)
SCAN_LIMIT = 500  # newest open questions compared per incoming question
MAX_QUESTION = 500
STATUSES = ("open", "answered", "dismissed", "never")

# Question words and fillers that don't identify a topic ("where do you live" vs "where
# does he live"): English plus common Hinglish. Kept short on purpose.
_STOPWORDS = frozenset(
    """a an the is are was were be been am do does did can could will would should shall
    you your yours he she they them his her their him it its i me my we our us to of in on
    at for with about and or if so as by from this that these those there what whats which
    who whom when where why how any some tell please also just really kindly
    hai hain ho tha thi kya kaun kaise kab kahan aap uska uski unka unki apka apki
    mujhe batao bataiye""".split()
)
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def normalize(text: str) -> str:
    """Lowercased, punctuation and stopwords stripped, tokens sorted and de-duplicated."""
    text = text.lower().replace("'", "").replace("’", "")
    tokens = {t for t in _TOKEN.findall(text) if t not in _STOPWORDS}
    return " ".join(sorted(tokens))


def _words(text: str) -> str:
    return " ".join(_TOKEN.findall(text.lower()))


def similarity(a: str, b: str) -> float:
    """Token-set Jaccard of two normalised strings; 0.0 when either is empty."""
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def find_group(db: Session, bot_id: str, normalized: str, raw: str) -> OpenQuestion | None:
    rows = db.scalars(
        select(OpenQuestion)
        .where(OpenQuestion.bot_id == bot_id, OpenQuestion.status == "open")
        .order_by(OpenQuestion.last_asked_at.desc())
        .limit(SCAN_LIMIT)
    )
    best, best_score = None, 0.0
    for row in rows:
        if normalized and row.normalized == normalized:
            return row
        if not normalized and _words(row.question) == _words(raw):
            return row  # all-stopword question: only an exact repeat groups
        score = similarity(row.normalized, normalized)
        if score >= SIMILARITY and score > best_score:
            best, best_score = row, score
    return best


def record(
    db: Session, bot_id: str, question: str, session_id: str | None, now: datetime | None = None
) -> tuple[OpenQuestion, bool]:
    """Count one more ask for the question's group, creating the group if needed.
    Returns (group, is_new)."""
    now = now or utcnow()
    text = question.strip()[:MAX_QUESTION]
    norm = normalize(text)
    row = find_group(db, bot_id, norm, text)
    if row is not None:
        row.ask_count += 1
        row.last_asked_at = now
        row.last_session_id = session_id
        row.updated_at = now
        db.flush()
        return row, False
    row = OpenQuestion(
        bot_id=bot_id,
        question=text,
        normalized=norm,
        ask_count=1,
        first_asked_at=now,
        last_asked_at=now,
        last_session_id=session_id,
        status="open",
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    return row, True


def should_notify(row: OpenQuestion, now: datetime | None = None) -> bool:
    """First ask of a group, then at most once per 24h."""
    if row.last_notified_at is None:
        return True
    return (now or utcnow()) - _aware(row.last_notified_at) >= NOTIFY_EVERY


def get(db: Session, bot_id: str, qid: str) -> OpenQuestion | None:
    return db.scalar(
        select(OpenQuestion).where(OpenQuestion.bot_id == bot_id, OpenQuestion.id == qid)
    )


def list_(db: Session, bot_id: str, status: str | None = "open", limit: int = 200):
    q = select(OpenQuestion).where(OpenQuestion.bot_id == bot_id)
    if status:
        q = q.where(OpenQuestion.status == status)
    q = q.order_by(OpenQuestion.ask_count.desc(), OpenQuestion.last_asked_at.desc()).limit(limit)
    return list(db.scalars(q))


def count_open(db: Session, bot_id: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(OpenQuestion)
            .where(OpenQuestion.bot_id == bot_id, OpenQuestion.status == "open")
        )
        or 0
    )


def set_status(db: Session, row: OpenQuestion, status: str) -> None:
    row.status = status
    row.updated_at = utcnow()
    db.flush()
