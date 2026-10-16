"""Draft = extracted items + temp ids + a match against the current profile.

Generic per section: a ``Matcher`` says how two entries are "the same thing" (key and,
for dated sections, a start month within +-1). Everything else (diffing, defaults,
validation, apply) is shared, so a new importer (GitHub projects, #10) needs no code
here.

Draft entry: ``{temp_id, data, match: {status: new|same|changed, existing_id?, diff?},
needs_review, reason?, kind?, snippet?, default_action}``. Defaults: new -> add,
changed -> update, same -> skip; needs_review and secondary e-mails -> skip.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.orm import Session

from mebot import channels
from mebot.imports.pipelines import Extracted, Item
from mebot.profile.data import load_profile
from mebot.profile.facts import normalize_skill
from mebot.profile.schemas import IdentityIn
from mebot.profile.sections import SECTIONS

SECTION_ORDER = (
    "identity",
    "experiences",
    "educations",
    "skills",
    "projects",
    "interests",
    "links",
    "notes",
)
PREFIX = {
    "identity": "i",
    "experiences": "e",
    "educations": "d",
    "skills": "s",
    "projects": "p",
    "interests": "h",
    "links": "c",
    "notes": "n",
}
IDENTITY_FIELDS = ("full_name", "headline", "location", "summary")


def norm(v) -> str:
    return re.sub(r"[^a-z0-9+#]+", " ", str(v or "").lower()).strip()


def _channel_key(d: dict) -> tuple:
    kind = d.get("kind") or "website"
    try:
        value = channels.normalize(kind, str(d.get("value") or ""))
    except channels.ChannelError:
        value = str(d.get("value") or "")
    return kind, value.lower().rstrip("/")


@dataclass(frozen=True)
class Matcher:
    key: Callable[[dict], object]
    # Fields the key is built from: equal once matched (aliases, case), so never diffed.
    fields: tuple[str, ...] = ()
    dated: bool = False  # also require start months within +-1 month (when both known)


MATCHERS: dict[str, Matcher] = {
    "experiences": Matcher(
        lambda d: (norm(d.get("company")), norm(d.get("title"))), ("company", "title"), True
    ),
    "educations": Matcher(
        lambda d: (norm(d.get("institution")), norm(d.get("degree"))), ("institution", "degree")
    ),
    "skills": Matcher(lambda d: normalize_skill(norm(d.get("name"))), ("name",)),
    "projects": Matcher(lambda d: norm(d.get("name")), ("name",)),
    "interests": Matcher(lambda d: norm(d.get("name")), ("name",)),
    "links": Matcher(_channel_key, ("kind", "value")),
}


def _month_idx(m: str | None) -> int | None:
    if not m or not re.match(r"^\d{4}-\d{2}$", m):
        return None
    y, mo = m.split("-")
    return int(y) * 12 + int(mo)


def _near(a: str | None, b: str | None) -> bool:
    ia, ib = _month_idx(a), _month_idx(b)
    return ia is None or ib is None or abs(ia - ib) <= 1


def _same_value(a, b) -> bool:
    if isinstance(a, list) or isinstance(b, list):
        return {norm(x) for x in a or []} == {norm(x) for x in b or []}
    if isinstance(a, str) or isinstance(b, str):
        return (
            " ".join(str(a or "").split()).casefold() == " ".join(str(b or "").split()).casefold()
        )
    return a == b


def diff(new: dict, old: dict, ignore: tuple[str, ...] = ()) -> dict:
    """Fields the import would change: only ones it actually has a value for."""
    return {
        k: {"from": old.get(k), "to": v}
        for k, v in new.items()
        if k not in ignore and v not in (None, "", []) and not _same_value(v, old.get(k))
    }


def merge(existing: dict, new: dict) -> dict:
    """An update keeps every existing field the import has no value for."""
    return {**existing, **{k: v for k, v in new.items() if v not in (None, "", [])}}


def find_match(slug: str, data: dict, existing: list[dict]) -> dict | None:
    m = MATCHERS.get(slug)
    if m is None:
        return None
    key = m.key(data)
    if not key or key == ("", "") or key == ("website", ""):
        return None
    for row in existing:
        if m.key(row) == key and (
            not m.dated or _near(data.get("start_month"), row.get("start_month"))
        ):
            return row
    return None


def validation_reason(slug: str, data: dict) -> str | None:
    sec = SECTIONS.get(slug)
    if sec is None:
        return None
    try:
        sec.schema.model_validate(data)
    except ValidationError as e:
        parts = []
        for err in e.errors():
            field = ".".join(str(p) for p in err["loc"]) or "item"
            msg = err["msg"].removeprefix("Value error, ")
            parts.append("needs " + field if err["type"] == "missing" else f"{field}: {msg}")
        return "Fix before adding: " + "; ".join(dict.fromkeys(parts))
    return None


def _entry(temp_id: str, item: Item, match: dict, reason: str | None = None) -> dict:
    needs_review = item.needs_review or reason is not None
    reasons = [r for r in (item.reason, reason) if r]
    out = {"temp_id": temp_id, "data": item.data, "match": match, "needs_review": needs_review}
    if reasons:
        out["reason"] = " · ".join(reasons)
    if item.kind:
        out["kind"] = item.kind
    if item.snippet:
        out["snippet"] = item.snippet
    status = match["status"]
    if needs_review or item.default_skip or status == "same":
        out["default_action"] = "skip"
    else:
        out["default_action"] = "update" if status == "changed" else "add"
    return out


def _identity_entries(proposed: dict, current: dict) -> list[dict]:
    out = []
    for field in IDENTITY_FIELDS:
        value = proposed.get(field)
        if not value:
            continue
        old = current.get(field) or ""
        if not old.strip():
            match = {"status": "new"}
        elif _same_value(value, old):
            match = {"status": "same"}
        else:
            match = {"status": "changed", "diff": {"value": {"from": old, "to": value}}}
        reason = None
        try:
            IdentityIn.model_validate({field: value})
        except ValidationError as e:
            reason = "Fix before adding: " + e.errors()[0]["msg"].removeprefix("Value error, ")
        out.append(_entry(f"i-{field}", Item(data={"field": field, "value": value}), match, reason))
    return out


def build(db: Session, bot_id: str, ex: Extracted) -> dict:
    profile = load_profile(db, bot_id)
    sections: dict[str, list[dict]] = {}
    if ex.identity:
        sections["identity"] = _identity_entries(ex.identity, profile.identity)
    for slug, items in ex.sections.items():
        entries = []
        for i, item in enumerate(items):
            temp_id = f"{PREFIX.get(slug, 'x')}{i + 1}"
            if slug == "notes":
                content = item.data.get("content", "")
                status = "same" if content and content in profile.notes else "new"
                entries.append(_entry(temp_id, item, {"status": status}))
                continue
            row = find_match(slug, item.data, profile.items(slug))
            if row is None:
                entries.append(
                    _entry(temp_id, item, {"status": "new"}, validation_reason(slug, item.data))
                )
                continue
            changes = diff(item.data, row, MATCHERS[slug].fields)
            if not changes:
                match = {"status": "same", "existing_id": row["id"]}
                entries.append(_entry(temp_id, item, match))
            else:
                match = {"status": "changed", "existing_id": row["id"], "diff": changes}
                merged = merge(row, item.data)
                entries.append(_entry(temp_id, item, match, validation_reason(slug, merged)))
        if entries:
            sections[slug] = entries
    return {"sections": {k: sections[k] for k in SECTION_ORDER if k in sections}}
