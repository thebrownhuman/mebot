"""Hallucination and privacy checks for LLM-extracted resume items.

Grounding: each item's key strings (company, title, institution, degree, project and
skill names, link values, the owner's name) must appear in the resume text, compared
case- and punctuation-insensitively with a fuzzy ratio >= 0.85, and every year in its
dates must appear too. Items that fail are kept but flagged ``needs_review`` (so they
default to Skip) with a reason, and the matching source line is kept for "Show in
source".

Privacy: personal-category text (mebot.guard.personal: date of birth, marital status,
religion, health, ...) and phone numbers are removed before the draft is stored.
"""

import re
from difflib import SequenceMatcher

from mebot.guard import personal
from mebot.imports.pipelines import Extracted, Item

THRESHOLD = 0.85
KEYS = {
    "experiences": ("company", "title"),
    "educations": ("institution", "degree"),
    "projects": ("name",),
    "skills": ("name",),
    "links": ("value",),
}
DATE_FIELDS = ("start_month", "end_month")
# Free text: offending sentences are cut. Any other field matching drops the item.
TEXT_FIELDS = {"description", "summary", "highlights"}
_TOKEN = re.compile(r"[a-z0-9]+")
_PHONE = re.compile(r"(?<![\w/])\+?\d[\d\s().-]{6,}\d(?![\w/])")
_SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n+")


def _norm_tokens(s: str) -> list[str]:
    return _TOKEN.findall(s.lower())


class Source:
    def __init__(self, text: str):
        self.text = text
        self.spans = [(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(text.lower())]
        self.words = [w for w, _, _ in self.spans]
        self.joined = " " + " ".join(self.words) + " "
        self.years = set(re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text))

    def _line_at(self, start: int, end: int) -> str:
        a = self.text.rfind("\n", 0, start) + 1
        b = self.text.find("\n", end)
        return self.text[a : b if b != -1 else len(self.text)].strip()[:300]

    def find(self, value: str) -> str | None:
        """The source line containing value (exact or fuzzy), or None."""
        want = _norm_tokens(value)
        if not want:
            return None
        n = len(want)
        needle = " " + " ".join(want) + " "
        pos = self.joined.find(needle)
        if pos != -1:
            i = self.joined[:pos].count(" ")  # token index of the match
            return self._line_at(self.spans[i][1], self.spans[i + n - 1][2])
        target = " ".join(want)
        best, best_i, best_len = 0.0, -1, n
        for size in {max(1, n - 1), n, n + 1}:
            for i in range(0, max(0, len(self.words) - size) + 1):
                cand = " ".join(self.words[i : i + size])
                m = SequenceMatcher(None, target, cand)
                if m.real_quick_ratio() < THRESHOLD or m.quick_ratio() < THRESHOLD:
                    continue
                r = m.ratio()
                if r > best:
                    best, best_i, best_len = r, i, size
        if best >= THRESHOLD:
            return self._line_at(self.spans[best_i][1], self.spans[best_i + best_len - 1][2])
        return None


def _scrub_text(value: str) -> str:
    # Whole sentences go: "Call +91 ..." minus the number still reads as an invitation.
    kept = [
        s
        for s in _SENTENCE.split(value)
        if s.strip() and not personal.classify(s) and not _PHONE.search(s)
    ]
    return " ".join(s.strip() for s in kept).strip()


def _strip_item(data: dict) -> dict | None:
    """The item without personal / phone data, or None when it is personal itself."""
    out = {}
    for k, v in data.items():
        if isinstance(v, list):
            v = [x for x in (_scrub_text(x) for x in v) if x]
        elif isinstance(v, str) and k in TEXT_FIELDS:
            v = _scrub_text(v)
        elif isinstance(v, str):
            if personal.classify(v) or (k != "value" and _PHONE.search(v)):
                return None
        if v not in ("", [], None):
            out[k] = v
    return out


def _years(data: dict) -> list[str]:
    return [data[f][:4] for f in DATE_FIELDS if isinstance(data.get(f), str)]


def check(slug: str, item: Item, src: Source) -> Item:
    reasons, snippet = [], None
    for key in KEYS.get(slug, ()):
        value = item.data.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        probe = value
        if slug == "links":
            probe = re.sub(r"^(https?://)?(www\.)?|^mailto:", "", value, flags=re.IGNORECASE)
        line = src.find(probe)
        if line is None:
            reasons.append(f"“{value}” isn't in your resume")
        elif snippet is None:
            snippet = line
    for year in _years(item.data):
        if year not in src.years:
            reasons.append(f"the year {year} isn't in your resume")
    if reasons:
        item.needs_review = True
        reason = "; ".join(dict.fromkeys(reasons))
        item.reason = reason[:1].upper() + reason[1:]
    item.snippet = snippet
    return item


def review(ex: Extracted, source: str) -> Extracted:
    src = Source(source)
    identity = {}
    for k, v in ex.identity.items():
        v = _scrub_text(v) if k == "summary" else v
        if not v or (k != "summary" and (personal.classify(v) or _PHONE.search(v))):
            continue
        identity[k] = v
    if identity.get("full_name") and src.find(identity["full_name"]) is None:
        identity.pop("full_name")  # never propose a name the resume doesn't contain
    ex.identity = identity
    for slug, items in ex.sections.items():
        kept = []
        for item in items:
            if slug == "links" and item.data.get("kind") == "phone":
                continue
            data = _strip_item(item.data)
            if data is None:
                continue
            item.data = data
            kept.append(check(slug, item, src))
        ex.sections[slug] = kept
    return ex
