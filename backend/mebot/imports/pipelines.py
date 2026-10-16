"""Import kinds and the background job that turns an upload into a reviewable draft.

A runner gets the upload's bytes (in memory only) and returns an ``Extracted``: plain
items per profile section. ``draft.build`` then matches them against the current
profile. New importers (GitHub, #10) register a ``Kind`` and a runner; nothing else in
the job / draft / apply flow is kind-specific.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from mebot.imports.filetype import ImportFailure

MB = 1024 * 1024
TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class Kind:
    name: str
    max_bytes: int
    accept: tuple[str, ...]  # sniffed types: pdf | docx | zip
    needs_llm: bool
    # "file": multipart upload via POST /import/{kind}; "json": its own endpoint.
    input: str = "file"


KINDS: dict[str, Kind] = {
    "resume": Kind("resume", 10 * MB, ("pdf", "docx"), needs_llm=True),
    "linkedin": Kind("linkedin", 50 * MB, ("zip",), needs_llm=False),
    # Repo URLs, not a file; the LLM is optional (deterministic fallback).
    "github": Kind("github", 0, (), needs_llm=False, input="json"),
}


@dataclass
class Item:
    """One proposed profile entry. ``data`` uses the section's input-schema field names."""

    data: dict
    needs_review: bool = False
    reason: str | None = None
    # Shown separately in review, e.g. "certification" inside educations.
    kind: str | None = None
    # The source text this item was matched to (resume "Show in source").
    snippet: str | None = None
    # Pre-selected action override (e.g. secondary e-mail addresses start unticked).
    default_skip: bool = False
    # Drop the item when it matches something already in the profile (skill proposals).
    only_if_new: bool = False
    # Why each piece was proposed, e.g. [{"tech": "FastAPI", "file": "requirements.txt"}].
    evidence: list[dict] | None = None


@dataclass
class Extracted:
    # identity field -> proposed value
    identity: dict[str, str] = field(default_factory=dict)
    # section slug (experiences, educations, skills, projects, interests, links, notes) -> items
    sections: dict[str, list[Item]] = field(default_factory=dict)
    source_text: str | None = None
    # Parts of the input that failed on their own, e.g. one repo of several:
    # [{"source": "owner/repo", "code": "REPO_NOT_FOUND", "message": "..."}]
    errors: list[dict] = field(default_factory=list)


@dataclass
class RunContext:
    filetype: str
    llm: object | None = None  # mebot.llm.service.ResolvedLLM when available
    # Kind-specific, in memory only (e.g. the GitHub token). Never stored or logged.
    options: dict = field(default_factory=dict)


Runner = Callable[[bytes, RunContext], Awaitable[Extracted]]
RUNNERS: dict[str, Runner] = {}


def register(kind: str, runner: Runner) -> None:
    RUNNERS[kind] = runner


async def process(app_state, bot_id: str, job_id: str, kind: str, data: bytes, ctx: RunContext):
    """Background task: run the importer, store the draft or the failure. Never raises.

    ``data`` is dropped when this returns; nothing about the file is logged."""
    from mebot.imports import draft
    from mebot.repos import import_jobs

    runner = app_state.import_runners.get(kind)
    code, message, built, source = None, None, None, None
    try:
        if runner is None:
            raise ImportFailure("UNSUPPORTED_FILE", "This import type isn't available.")
        extracted = await asyncio.wait_for(runner(data, ctx), TIMEOUT_SECONDS)
        with app_state.session_factory() as db:
            built = draft.build(db, bot_id, extracted)
        source = extracted.source_text
    except ImportFailure as e:
        code, message = e.code, e.message
    except TimeoutError:
        code, message = "EXTRACTION_FAILED", "The import took too long. Please try again."
    except Exception:  # noqa: BLE001 - details may echo file content; keep them out
        code, message = "EXTRACTION_FAILED", "Something went wrong reading that file."
    finally:
        del data
    with app_state.session_factory() as db:
        job = import_jobs.get(db, bot_id, job_id)
        if job is None or job.status != "processing":  # discarded meanwhile
            return
        if code:
            import_jobs.fail(db, job, code, message)
        else:
            import_jobs.finish(db, job, built, source)
        db.commit()
