"""Owner-only imports: upload a resume / LinkedIn export, review the draft, apply it.

Uploads are read into memory, checked by magic bytes, hashed and handed to a
background task; the file itself is never stored or logged. Starlette may spool a
large multipart body to an OS temp file while parsing; that file is closed (deleted)
when the request ends. Content-Length is required so nothing beyond the size limit is
ever read.
"""

import hashlib
import re
from datetime import UTC
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from mebot.db import get_db
from mebot.deps import csrf_on_mutation, get_current_admin, get_current_bot, require_setup_done
from mebot.errors import ApiError
from mebot.imports import apply as applier
from mebot.imports.filetype import ImportFailure, check_pdf, sniff
from mebot.imports.pipelines import KINDS, RunContext, process
from mebot.llm import service as llm
from mebot.models import Bot, ImportJob
from mebot.repos import import_jobs, logs

router = APIRouter(
    prefix="/api/admin/import",
    dependencies=[
        Depends(require_setup_done),
        Depends(get_current_admin),
        Depends(csrf_on_mutation),
    ],
)

CHUNK = 64 * 1024
FORM_OVERHEAD = 64 * 1024  # multipart boundaries + headers on top of the file


def _iso(dt) -> str | None:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def safe_filename(name: str | None) -> str:
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[^\w .()\-]", "_", base).strip(" .")
    return (base or "upload")[:200]


def job_summary(job: ImportJob) -> dict:
    import json

    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "filename": job.filename,
        "size_bytes": job.size_bytes,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "applied_summary": json.loads(job.applied_summary) if job.applied_summary else None,
        "created_at": _iso(job.created_at),
        "expires_at": _iso(job.expires_at),
    }


def _fail(e: ImportFailure) -> ApiError:
    return ApiError(e.status, e.code, e.message)


async def _read_upload(request: Request, max_bytes: int) -> tuple[bytes, str]:
    too_big = ApiError(
        413, "FILE_TOO_LARGE", f"That file is too large (max {max_bytes // (1024 * 1024)} MB)."
    )
    length = request.headers.get("content-length")
    if not length or not length.isdigit():
        raise ApiError(411, "LENGTH_REQUIRED", "Upload with a Content-Length header.")
    if int(length) > max_bytes + FORM_OVERHEAD:
        raise too_big
    form = await request.form(max_files=1, max_fields=1)
    try:
        upload = form.get("file")
        if upload is None or isinstance(upload, str):
            raise ApiError(422, "VALIDATION_ERROR", "Choose a file to upload.")
        buf = bytearray()
        while chunk := await upload.read(CHUNK):
            buf += chunk
            if len(buf) > max_bytes:
                raise too_big
        if not buf:
            raise ApiError(422, "VALIDATION_ERROR", "That file is empty.")
        return bytes(buf), safe_filename(upload.filename)
    finally:
        await form.close()


@router.post("/{kind}", status_code=202)
async def upload(
    kind: str,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    spec = KINDS.get(kind)
    if spec is None or kind not in request.app.state.import_runners:
        raise ApiError(404, "NOT_FOUND", "Unknown import type")
    resolved = None
    if spec.needs_llm:
        status, _, resolved = llm.load(db, bot.id, request.app.state.secret_key)
        if resolved is None:
            raise ApiError(
                422,
                "LLM_NOT_CONFIGURED",
                "Resume import uses your AI provider. Set it up in Admin -> AI Provider first.",
            )
    if import_jobs.processing(db, bot.id) is not None:
        db.commit()
        raise ApiError(409, "IMPORT_IN_PROGRESS", "Another import is still running.")
    db.commit()  # a stale job may have been failed above

    data, filename = await _read_upload(request, spec.max_bytes)
    try:
        ftype = sniff(data)
        if ftype not in spec.accept:
            raise ImportFailure(
                "UNSUPPORTED_FILE",
                "Upload a PDF or Word .docx resume."
                if kind == "resume"
                else "Upload the .zip file LinkedIn emailed you.",
                415,
            )
        if ftype == "pdf":
            check_pdf(data)
    except ImportFailure as e:
        raise _fail(e) from None

    digest = hashlib.sha256(data).hexdigest()
    same = import_jobs.ready_with_hash(db, bot.id, kind, digest)
    if same is not None:
        return JSONResponse(job_summary(same), status_code=200)

    wait = request.app.state.import_limiter.hit(bot.id)
    if wait is not None:
        raise ApiError(
            429,
            "RATE_LIMITED",
            "Too many imports this hour. Please try again later.",
            headers={"Retry-After": str(wait)},
        )
    job = import_jobs.create(db, bot.id, kind, filename=filename, sha256=digest, size=len(data))
    # Kind and size only: never the file name or content.
    logs.add(db, bot.id, None, "IMPORT_STARTED", detail=f"{kind} {len(data)}")
    db.commit()
    background.add_task(
        process, request.app.state, bot.id, job.id, kind, data, RunContext(ftype, resolved)
    )
    return {"id": job.id, "status": job.status}


@router.get("/jobs")
def list_jobs(db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    import_jobs.purge_expired(db)
    db.commit()
    return {"items": [job_summary(j) for j in import_jobs.latest(db, bot.id)]}


def _job_or_404(db: Session, bot: Bot, job_id: str) -> ImportJob:
    job = import_jobs.get(db, bot.id, job_id)
    if job is None:
        raise ApiError(404, "NOT_FOUND", "Import not found")
    return job


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    import_jobs.purge_expired(db)
    db.commit()
    job = _job_or_404(db, bot, job_id)
    body = job_summary(job)
    body["draft"] = import_jobs.draft_of(job)
    body["source_text"] = job.source_text
    return body


@router.delete("/jobs/{job_id}", status_code=204)
def discard_job(job_id: str, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    import_jobs.discard(db, _job_or_404(db, bot, job_id))
    db.commit()
    return Response(status_code=204)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temp_id: str = Field(max_length=40)
    action: Literal["add", "update", "skip"]
    data: dict | None = None


class ApplyIn(BaseModel):
    decisions: list[Decision] = Field(max_length=2000)


@router.post("/jobs/{job_id}/apply")
def apply_job(
    job_id: str, req: ApplyIn, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)
):
    import_jobs.purge_expired(db)
    job = _job_or_404(db, bot, job_id)
    if job.status == "applied":
        raise ApiError(409, "ALREADY_APPLIED", "This import was already applied.")
    if job.status != "ready":
        message = (
            "This import expired. Please upload the file again."
            if job.status == "expired"
            else "This import isn't ready to apply."
        )
        raise ApiError(409, "IMPORT_NOT_READY", message)
    draft = import_jobs.draft_of(job) or {"sections": {}}
    known = {e["temp_id"] for entries in draft["sections"].values() for e in entries}
    decisions = {}
    for d in req.decisions:
        if d.temp_id not in known:
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                "Invalid request",
                [{"field": d.temp_id, "message": "not in this import"}],
            )
        decisions[d.temp_id] = d.model_dump()
    plan = applier.plan(db, bot.id, draft, decisions)
    if plan.errors:
        db.rollback()
        raise ApiError(
            422, "VALIDATION_ERROR", "Some items need fixing; nothing was applied.", plan.errors
        )
    try:
        summary = applier.execute(db, bot.id, plan)
        import_jobs.mark_applied(db, job, summary)
        logs.add(db, bot.id, None, "IMPORT_APPLIED", detail=f"{job.kind}")
        logs.add(db, bot.id, None, "profile_updated", detail="import")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"applied": summary}
