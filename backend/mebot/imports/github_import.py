"""The GitHub import runner: fetch each repo, detect its tech, draft a project entry.

One project item per repo plus skill proposals (detected tech not already a skill,
unticked by default). A repo that fails (missing, private, rate limit, timeout) is
reported in the draft's errors and the others still import; a rate limit stops the
remaining repos. The whole job is capped at JOB_SECONDS.
"""

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta

from mebot.imports import github_draft
from mebot.imports.filetype import ImportFailure
from mebot.imports.github import GitHubClient, GitHubError, RepoData, repo_url
from mebot.imports.pipelines import Extracted, Item, RunContext, register
from mebot.imports.techmap import Detection, detect

JOB_SECONDS = 90
ACTIVE_WITHIN = timedelta(days=183)
NO_AI = "AI summary unavailable: the summary is the repo description"
LAYER_CATEGORY = {
    "frontend": "framework",
    "backend": "framework",
    "data_ai": "framework",
    "infra": "cloud",
    "tooling": "tool",
}


def humanise(name: str) -> str:
    return re.sub(r"[-_]+", " ", name).strip() or name


def _month(iso) -> str | None:
    s = str(iso or "")
    return s[:7] if re.match(r"^\d{4}-\d{2}", s) else None


def _http_url(v) -> str | None:
    v = str(v or "").strip()
    return v if re.match(r"^https?://[^\s/]+", v, re.IGNORECASE) else None


def status_for(meta: dict, now: datetime) -> str:
    if meta.get("archived"):
        return "archived"
    try:
        pushed = datetime.fromisoformat(str(meta.get("pushed_at")).replace("Z", "+00:00"))
    except ValueError:
        return "completed"
    return "active" if now - pushed <= ACTIVE_WITHIN else "completed"


def deterministic_fields(data: RepoData, det: Detection, now: datetime) -> dict:
    meta = data.meta
    name = str(meta.get("name") or data.repo)
    return {
        "name": humanise(name),
        "tagline": (str(meta.get("description") or "").strip() or None),
        "tech": det.tech,
        "repo_url": repo_url(data.owner, name),
        "live_url": _http_url(meta.get("homepage")),
        "start_month": _month(meta.get("created_at")),
        "end_month": _month(meta.get("pushed_at")) if meta.get("archived") else None,
        "status": status_for(meta, now),
    }


async def project_item(data: RepoData, ctx: RunContext, now: datetime) -> tuple[Item, Detection]:
    det = detect(data.files, data.paths, data.languages)
    fields = deterministic_fields(data, det, now)
    reasons: list[str] = []
    prose = None
    if ctx.llm is not None:
        prose = await github_draft.draft_prose(
            ctx.llm.client(), ctx.llm.model, data.meta, det, data.readme
        )
    if prose is not None:
        reasons += github_draft.check(prose, det, data.readme, data.meta)
        fields.update(github_draft.clean(prose))
    else:
        reasons.append(
            NO_AI if ctx.llm is None else "AI summary failed: the summary is the repo description"
        )
        fields["summary"] = fields["tagline"] or ""
    if not data.readme:
        reasons.append("no README: check the summary")
    if not fields.get("summary"):
        reasons.append("add a summary")
    reasons += det.notes + data.notes
    data_out = {k: v for k, v in fields.items() if v not in (None, "", [])}
    item = Item(
        data=data_out,
        needs_review=bool(reasons),
        reason="; ".join(dict.fromkeys(reasons)) if reasons else None,
        evidence=det.evidence or None,
    )
    if item.reason:
        item.reason = item.reason[:1].upper() + item.reason[1:]
    return item, det


def skill_items(detections: list[Detection]) -> list[Item]:
    seen: dict[str, Item] = {}
    for det in detections:
        for lang in det.languages:
            seen.setdefault(lang.lower(), Item(data={"name": lang, "category": "language"}))
        for layer, names in det.by_layer.items():
            for name in names:
                seen.setdefault(
                    name.lower(), Item(data={"name": name, "category": LAYER_CATEGORY[layer]})
                )
    for item in seen.values():
        item.default_skip = True  # the owner ticks what they want listed as a skill
        item.only_if_new = True
        item.evidence = [
            e
            for det in detections
            for e in det.evidence
            if e["tech"].lower() == item.data["name"].lower()
        ][:5] or None
    return list(seen.values())


async def run(payload: bytes, ctx: RunContext) -> Extracted:
    repos = [tuple(r) for r in json.loads(payload)["repos"]]
    now = datetime.now(UTC)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + JOB_SECONDS
    ex = Extracted()
    projects: list[Item] = []
    detections: list[Detection] = []
    stop: GitHubError | None = None
    async with GitHubClient(ctx.options.get("token")) as gh:
        for owner, repo in repos:
            source = f"{owner}/{repo}"
            if stop is not None:
                ex.errors.append({"source": source, "code": stop.code, "message": stop.message})
                continue
            remaining = deadline - loop.time()
            if remaining <= 0:
                ex.errors.append(
                    {"source": source, "code": "GITHUB_UNAVAILABLE", "message": "Ran out of time."}
                )
                continue

            async def one(o=owner, r=repo):
                return await project_item(await gh.fetch_repo(o, r), ctx, now)

            try:
                item, det = await asyncio.wait_for(one(), remaining)
            except GitHubError as e:
                ex.errors.append({"source": source, "code": e.code, "message": e.message})
                if e.code == "GITHUB_RATE_LIMITED":
                    stop = e
                continue
            except TimeoutError:
                ex.errors.append(
                    {"source": source, "code": "GITHUB_UNAVAILABLE", "message": "Ran out of time."}
                )
                continue
            projects.append(item)
            detections.append(det)
    if not projects:
        first = (
            ex.errors[0]
            if ex.errors
            else {"code": "GITHUB_UNAVAILABLE", "message": "Nothing imported."}
        )
        raise ImportFailure(first["code"], first["message"])
    ex.sections["projects"] = projects
    ex.sections["skills"] = skill_items(detections)
    return ex


register("github", run)
