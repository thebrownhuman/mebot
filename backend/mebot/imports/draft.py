"""Draft = extracted items + temp ids + a match against the current profile."""

from sqlalchemy.orm import Session

from mebot.imports.pipelines import Extracted, Item

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


def _entry(temp_id: str, item: Item) -> dict:
    out = {
        "temp_id": temp_id,
        "data": item.data,
        "match": {"status": "new"},
        "needs_review": item.needs_review,
    }
    if item.reason:
        out["reason"] = item.reason
    if item.kind:
        out["kind"] = item.kind
    if item.snippet:
        out["snippet"] = item.snippet
    out["default_action"] = "skip" if item.needs_review or item.default_skip else "add"
    return out


def build(db: Session, bot_id: str, ex: Extracted) -> dict:
    sections: dict[str, list[dict]] = {}
    if ex.identity:
        sections["identity"] = [
            _entry(f"i-{k}", Item(data={"field": k, "value": v})) for k, v in ex.identity.items()
        ]
    for slug, items in ex.sections.items():
        if items:
            sections[slug] = [
                _entry(f"{PREFIX.get(slug, 'x')}{i + 1}", it) for i, it in enumerate(items)
            ]
    return {"sections": {k: sections[k] for k in SECTION_ORDER if k in sections}}
