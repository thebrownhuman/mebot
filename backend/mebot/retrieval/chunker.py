"""Profile -> chunks. One chunk per natural item; each reads on its own (section heading +
item title), so a retrieved chunk makes sense without its neighbours.

Pure functions of ProfileData: no DB, no network. ``order`` is the position in the rendered
profile, so selected chunks can be shown in profile order rather than score order.
"""

import hashlib
from dataclasses import dataclass

from mebot.persona import display_name
from mebot.profile import render
from mebot.profile.data import ProfileData

NOTES_CHUNK_CHARS = 1100  # ~275 tokens at ~4 chars/token, plus the heading
HEADINGS = {
    "experiences": "EXPERIENCE",
    "educations": "EDUCATION",
    "skills": "SKILLS",
    "projects": "PROJECTS",
    "interests": "INTERESTS & HOBBIES",
    "faqs": "FAQ",
    "learned": "LEARNED FACTS",
    "notes": "NOTES",
}
SECTION_ORDER = tuple(HEADINGS)  # the order render_profile() prints them in


@dataclass(frozen=True)
class Chunk:
    section: str
    item_key: str
    title: str
    text: str
    content_hash: str
    order: int  # position in the profile (section order, then item order)

    @property
    def tokens(self) -> int:
        return render.approx_tokens(self.text)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _key(slug: str, item: dict, index: int) -> str:
    return f"{slug}:{item.get('id') or index}"


def _make(section: str, key: str, title: str, body: str, order: int) -> Chunk:
    text = f"[{HEADINGS[section]}] {title}\n{body}"
    return Chunk(section, key, title, text, _hash(text), order)


def _body(lines: list[str | None]) -> str:
    return "\n".join(ln for ln in lines if ln)


def _split_notes(notes: str) -> list[str]:
    parts: list[str] = []
    cur = ""
    for para in (p.strip() for p in notes.split("\n\n")):
        while len(para) > NOTES_CHUNK_CHARS:  # one huge paragraph: cut at a word boundary
            cut = para.rfind(" ", 0, NOTES_CHUNK_CHARS)
            cut = cut if cut > 0 else NOTES_CHUNK_CHARS
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(para[:cut].strip())
            para = para[cut:].strip()
        if not para:
            continue
        if cur and len(cur) + len(para) + 2 > NOTES_CHUNK_CHARS:
            parts.append(cur)
            cur = ""
        cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        parts.append(cur)
    return parts


def build_chunks(p: ProfileData) -> list[Chunk]:
    out: list[Chunk] = []

    def add(section: str, key: str, title: str, body: str):
        out.append(_make(section, key, title, body, len(out)))

    for i, e in enumerate(p.items("experiences")):
        add(
            "experiences",
            _key("experiences", e, i),
            f"{e['title']} at {e['company']}",
            _body(render.experience_lines(e)),
        )
    for i, e in enumerate(p.items("educations")):
        degree = e["degree"] + (f" in {e['field']}" if e.get("field") else "")
        add(
            "educations",
            _key("educations", e, i),
            f"{degree}, {e['institution']}",
            _body(render.education_lines(e)),
        )
    groups: dict[str, list[dict]] = {}
    for s in p.items("skills"):
        groups.setdefault(s.get("category") or "other", []).append(s)
    for cat, skills in groups.items():
        add(
            "skills",
            f"skills:{cat}",
            f"{cat.capitalize()} skills",
            _body([render.skill_line(s) for s in skills]),
        )
    for i, pr in enumerate(p.items("projects")):
        add(
            "projects",
            _key("projects", pr, i),
            pr["name"],
            _body(render.project_lines(pr)),
        )
    kinds: dict[str, list[dict]] = {}
    for it in p.items("interests"):
        kinds.setdefault(it["kind"], []).append(it)
    for kind, items in kinds.items():
        add(
            "interests",
            f"interests:{kind}",
            kind.capitalize(),
            _body([render.interest_line(it) for it in items]),
        )
    for i, f in enumerate(p.items("faqs")):
        add("faqs", _key("faqs", f, i), f["question"], render.faq_text(f))
    for text in p.learned:
        add("learned", f"learned:{_hash(text)[:12]}", text[:60], f"- {text}")
    for n, part in enumerate(_split_notes(p.notes.strip()), 1):
        add("notes", f"notes:{n}", f"Notes (part {n})", part)
    return out


def outline(p: ProfileData) -> str:
    """Section names + item titles: tells the model what exists even when the details of an
    item were not retrieved for this question."""
    lines: list[str] = []

    def row(label: str, names: list[str]):
        if names:
            lines.append(f"{label}: " + "; ".join(names))

    row("Experience", [f"{e['title']} at {e['company']}" for e in p.items("experiences")])
    row(
        "Education",
        [
            e["degree"] + (f" in {e['field']}" if e.get("field") else "") + f", {e['institution']}"
            for e in p.items("educations")
        ],
    )
    row("Skills", [s["name"] for s in p.items("skills")])
    row("Projects", [pr["name"] for pr in p.items("projects")])
    row("Interests", [i["name"] for i in p.items("interests")])
    row("FAQ topics", [f["question"] for f in p.items("faqs")])
    if p.learned:
        n = len(p.learned)
        lines.append(f"Learned facts: {n} confirmed fact{'s' if n != 1 else ''}")
    if p.notes.strip():
        lines.append("Notes: free-text notes")
    if not lines:
        return ""
    who = display_name(p.identity)
    head = (
        f"=== PROFILE OUTLINE (everything {who} has listed; details are retrieved per question) ==="
    )
    return head + "\n" + "\n".join(lines)
