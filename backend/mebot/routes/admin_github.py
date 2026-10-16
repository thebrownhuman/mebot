"""GitHub import inputs: repo URLs (and, for the picker, a user's public repos).

The job itself runs through the shared import pipeline (kind='github'); review, apply,
discard and expiry are the #9 endpoints.
"""

import hashlib
import json
import re

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mebot.db import get_db
from mebot.deps import csrf_on_mutation, get_current_admin, get_current_bot, require_setup_done
from mebot.errors import ApiError
from mebot.imports import github
from mebot.imports.filetype import ImportFailure
from mebot.imports.pipelines import RunContext, process
from mebot.llm import service as llm
from mebot.models import Bot
from mebot.repos import import_jobs, logs

router = APIRouter(
    prefix="/api/admin",
    dependencies=[
        Depends(require_setup_done),
        Depends(get_current_admin),
        Depends(csrf_on_mutation),
    ],
)


class GithubImportIn(BaseModel):
    repo_urls: list[str] = Field(max_length=100)


def resolve_token(request: Request, db: Session, bot_id: str) -> str | None:
    """The token for GitHub's rate limits: the admin-saved one, else GITHUB_TOKEN."""
    return request.app.state.settings.github_token or None


def _parse_all(urls: list[str]) -> list[tuple[str, str]]:
    if not urls:
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "Add at least one repo URL.",
            [{"field": "repo_urls", "message": "required"}],
        )
    repos: list[tuple[str, str]] = []
    errors = []
    for i, raw in enumerate(urls):
        try:
            o, r = github.parse_repo_url(raw)
        except ImportFailure as e:
            errors.append({"field": f"repo_urls.{i}", "message": e.message})
            continue
        if (o.lower(), r.lower()) not in {(a.lower(), b.lower()) for a, b in repos}:
            repos.append((o, r))
    if errors:
        raise ApiError(422, "INVALID_REPO_URL", "Some repo URLs aren't valid.", errors)
    if len(repos) > github.MAX_REPOS:
        raise ApiError(
            422,
            "TOO_MANY_REPOS",
            f"Import at most {github.MAX_REPOS} repos at a time.",
            [{"field": "repo_urls", "message": f"max {github.MAX_REPOS}"}],
        )
    return repos


@router.post("/import/github", status_code=202)
async def import_github(
    req: GithubImportIn,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    if "github" not in request.app.state.import_runners:
        raise ApiError(404, "NOT_FOUND", "Unknown import type")
    repos = _parse_all(req.repo_urls)
    if import_jobs.processing(db, bot.id) is not None:
        db.commit()
        raise ApiError(409, "IMPORT_IN_PROGRESS", "Another import is still running.")
    wait = request.app.state.import_limiter.hit(bot.id)
    if wait is not None:
        raise ApiError(
            429,
            "RATE_LIMITED",
            "Too many imports this hour. Please try again later.",
            headers={"Retry-After": str(wait)},
        )
    # No sha256 dedupe for GitHub: the repos are live, a re-import should re-read them.
    _, _, resolved = llm.load(db, bot.id, request.app.state.secret_key)
    names = ", ".join(f"{o}/{r}" for o, r in repos)
    payload = json.dumps({"repos": [[o, r] for o, r in repos]}).encode()
    job = import_jobs.create(
        db,
        bot.id,
        "github",
        filename=names[:200],
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(repos),
    )
    logs.add(db, bot.id, None, "IMPORT_STARTED", detail=f"github {len(repos)}")
    db.commit()
    ctx = RunContext("json", resolved, {"token": resolve_token(request, db, bot.id)})
    background.add_task(process, request.app.state, bot.id, job.id, "github", payload, ctx)
    return {"id": job.id, "status": job.status}


_USERNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


def _repo_row(d: dict) -> dict:
    return {
        "name": d.get("name"),
        "full_name": d.get("full_name"),
        "description": d.get("description"),
        "language": d.get("language"),
        "stars": int(d.get("stargazers_count") or 0),
        "pushed_at": d.get("pushed_at"),
        "fork": bool(d.get("fork")),
        "archived": bool(d.get("archived")),
        "html_url": github.repo_url(*str(d.get("full_name") or "/").split("/", 1)),
    }


@router.get("/import/github/repos")
async def github_repos(
    request: Request,
    username: str = Query(max_length=39),
    include_forks: bool = Query(False),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    """A user's public repos for the picker: non-archived first, then stars, then push."""
    if not _USERNAME.match(username):
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "That isn't a GitHub username.",
            [{"field": "username", "message": "invalid"}],
        )
    try:
        async with github.GitHubClient(resolve_token(request, db, bot.id)) as gh:
            rows = await gh.user_repos(username)
    except github.GitHubError as e:
        raise ApiError(e.status if e.status != 422 else 502, e.code, e.message) from None
    rows = [
        r for r in rows if r.get("private") is not True and (include_forks or not r.get("fork"))
    ]
    # Stable sorts: newest push, then by stars, then non-archived first.
    rows.sort(key=lambda d: str(d.get("pushed_at") or ""), reverse=True)
    rows.sort(key=lambda d: int(d.get("stargazers_count") or 0), reverse=True)
    rows.sort(key=lambda d: bool(d.get("archived")))
    return {"items": [_repo_row(d) for d in rows[:100]]}
