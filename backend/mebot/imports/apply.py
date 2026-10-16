"""Apply the owner's review decisions to the profile, all or nothing.

Every decision is validated with the section's #4 schema first; any failure means a
422 listing each bad item and nothing is written. Updates change only the fields the
import proposed (the diff) plus the owner's inline edits; identity fields are written
one by one, and only those with an add/update decision.
"""

from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy.orm import Session

from mebot.imports.draft import merge
from mebot.profile.data import load_profile
from mebot.profile.schemas import IdentityIn, NotesIn
from mebot.profile.sections import SECTIONS
from mebot.repos import profile_items as repo

ACTIONS = ("add", "update", "skip")


@dataclass
class Plan:
    errors: list[dict] = field(default_factory=list)
    ops: list[tuple] = field(default_factory=list)  # (kind, slug, payload...)


def _errors(temp_id: str, e: ValidationError) -> list[dict]:
    return [
        {
            "field": ".".join([temp_id, *(str(p) for p in err["loc"])]),
            "message": err["msg"].removeprefix("Value error, "),
        }
        for err in e.errors()
    ]


def _err(temp_id: str, message: str) -> dict:
    return {"field": temp_id, "message": message}


def plan(db: Session, bot_id: str, draft: dict, decisions: dict[str, dict]) -> Plan:
    p = Plan()
    profile = load_profile(db, bot_id)
    identity_changes: dict[str, str] = {}
    counts: dict[str, int] = {}
    for slug, entries in draft.get("sections", {}).items():
        for entry in entries:
            tid = entry["temp_id"]
            dec = decisions.get(tid)
            action = dec["action"] if dec else "skip"
            if action == "skip":
                continue
            data = dec.get("data") if dec and dec.get("data") is not None else entry["data"]
            existing_id = entry["match"].get("existing_id")
            if slug == "identity":
                field_name = entry["data"]["field"]
                value = data.get("value") if isinstance(data, dict) else None
                identity_changes[field_name] = value or ""
                continue
            if slug == "notes":
                content = str((data or {}).get("content", "")).strip()
                combined = profile.notes + "\n\n" + content
                problem = validate_notes(combined) if content else "empty"
                if problem:
                    p.errors.append(_err(tid, problem))
                else:
                    p.ops.append(("notes", slug, tid, content))
                continue
            sec = SECTIONS.get(slug)
            if sec is None:
                p.errors.append(_err(tid, "unknown section"))
                continue
            if action == "update":
                row = next((r for r in profile.items(slug) if r["id"] == existing_id), None)
                if row is None:
                    p.errors.append(_err(tid, "the item to update no longer exists"))
                    continue
                if dec and dec.get("data") is not None:
                    payload = merge(row, data)  # the owner edited it: take their version
                else:
                    proposed = entry["match"].get("diff", {})
                    payload = merge(row, {k: v["to"] for k, v in proposed.items()})
            else:
                payload = data
            try:
                model = sec.schema.model_validate(payload)
            except ValidationError as e:
                p.errors.extend(_errors(tid, e))
                continue
            if action == "add":
                counts[slug] = counts.get(slug, 0) + 1
                if len(profile.items(slug)) + counts[slug] > sec.limit:
                    p.errors.append(_err(tid, f"at most {sec.limit} items in {slug}"))
                    continue
            p.ops.append((action, slug, tid, model, existing_id))
    if identity_changes:
        current = {k: v for k, v in profile.identity.items() if k in IdentityIn.model_fields}
        try:
            model = IdentityIn.model_validate({**current, **identity_changes})
        except ValidationError as e:
            p.errors.extend(_errors("identity", e))
        else:
            p.ops.append(("identity", "identity", None, model, sorted(identity_changes)))
    return p


def execute(db: Session, bot_id: str, p: Plan) -> dict:
    summary: dict[str, dict[str, int]] = {}

    def bump(slug: str, key: str, n: int = 1):
        summary.setdefault(slug, {"added": 0, "updated": 0})[key] += n

    for op in p.ops:
        kind, slug = op[0], op[1]
        if kind == "identity":
            repo.put_identity(db, bot_id, op[3])
            bump("identity", "updated", len(op[4]))
        elif kind == "notes":
            row = repo.get_notes(db, bot_id)
            current = row.content if row else ""
            content = (current.rstrip() + "\n\n" + op[3]).strip() if current.strip() else op[3]
            repo.put_notes(db, bot_id, NotesIn(content=content))
            bump("notes", "updated" if current.strip() else "added")
        elif kind == "add":
            repo.create(db, SECTIONS[slug], bot_id, op[3])
            bump(slug, "added")
        elif kind == "update":
            sec = SECTIONS[slug]
            row = repo.get(db, sec, bot_id, op[4])
            repo.update(db, sec, row, op[3])
            bump(slug, "updated")
    return summary


def validate_notes(content: str) -> str | None:
    try:
        NotesIn(content=content)
    except ValidationError:
        return "notes would be too long"
    return None
