"""Import jobs. Statuses: processing -> ready -> applied, or failed / expired.

Content (draft, source_text) lives at most TTL; expiry nulls it and keeps the row.
A job stuck in `processing` past STALE (crashed worker) counts as failed.
"""

import json
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from mebot.models import ImportJob, utcnow

TTL = timedelta(days=7)
STALE = timedelta(minutes=10)


def create(db: Session, bot_id: str, kind: str, *, filename: str, sha256: str, size: int):
    now = utcnow()
    job = ImportJob(
        bot_id=bot_id,
        kind=kind,
        status="processing",
        filename=filename,
        sha256=sha256,
        size_bytes=size,
        created_at=now,
        updated_at=now,
        expires_at=now + TTL,
    )
    db.add(job)
    db.flush()
    return job


def get(db: Session, bot_id: str, job_id: str) -> ImportJob | None:
    return db.scalar(select(ImportJob).where(ImportJob.bot_id == bot_id, ImportJob.id == job_id))


def latest(db: Session, bot_id: str, limit: int = 20) -> list[ImportJob]:
    return list(
        db.scalars(
            select(ImportJob)
            .where(ImportJob.bot_id == bot_id)
            .order_by(ImportJob.created_at.desc(), ImportJob.id)
            .limit(limit)
        )
    )


def processing(db: Session, bot_id: str) -> ImportJob | None:
    """The bot's running job, if any. Stale ones are failed on the way."""
    job = db.scalar(
        select(ImportJob).where(ImportJob.bot_id == bot_id, ImportJob.status == "processing")
    )
    if job is not None and job.updated_at < utcnow() - STALE:
        fail(db, job, "EXTRACTION_FAILED", "The import stopped unexpectedly. Please upload again.")
        return None
    return job


def ready_with_hash(db: Session, bot_id: str, kind: str, sha256: str) -> ImportJob | None:
    return db.scalar(
        select(ImportJob).where(
            ImportJob.bot_id == bot_id,
            ImportJob.kind == kind,
            ImportJob.sha256 == sha256,
            ImportJob.status == "ready",
            ImportJob.expires_at > utcnow(),
        )
    )


def finish(db: Session, job: ImportJob, draft: dict, source_text: str | None = None) -> None:
    job.status = "ready"
    job.draft = json.dumps(draft, ensure_ascii=False)
    job.source_text = source_text
    job.updated_at = utcnow()
    db.flush()


def fail(db: Session, job: ImportJob, code: str, message: str) -> None:
    job.status = "failed"
    job.error_code = code
    job.error_message = message
    job.draft = job.source_text = None
    job.updated_at = utcnow()
    db.flush()


def mark_applied(db: Session, job: ImportJob, summary: dict) -> None:
    job.status = "applied"
    job.applied_summary = json.dumps(summary)
    job.draft = job.source_text = None  # the profile now holds the data
    job.updated_at = utcnow()
    db.flush()


def discard(db: Session, job: ImportJob) -> None:
    db.delete(job)
    db.flush()


def purge_expired(db: Session) -> int:
    """Null the content of jobs past expires_at; the rows stay as `expired`."""
    now = utcnow()
    result = db.execute(
        update(ImportJob)
        .where(ImportJob.expires_at <= now, ImportJob.status.in_(("ready", "failed", "processing")))
        .values(status="expired", draft=None, source_text=None, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount


def draft_of(job: ImportJob) -> dict | None:
    return json.loads(job.draft) if job.draft else None
