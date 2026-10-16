"""LinkedIn "Get a copy of your data" ZIP -> draft. Deterministic: no LLM, no network.

The ZIP is read in memory. Only the allow-listed CSVs below are ever opened; messages,
connections, invitations, phone numbers and everything else in the export are skipped
by name before any of their bytes are read. Guards: path traversal, entry count, total
size and per-entry compression ratio (zip bombs).
"""

import csv
import io
import re
import zipfile

from mebot.imports.filetype import ImportFailure
from mebot.imports.pipelines import Extracted, Item, RunContext, register

MAX_ENTRIES = 1000
MAX_TOTAL = 200 * 1024 * 1024
MAX_RATIO = 100
RATIO_MIN_SIZE = 64 * 1024  # tiny entries compress absurdly well; only check real ones
MAX_CSV = 20 * 1024 * 1024

ALLOWED = {
    "profile.csv": "profile",
    "positions.csv": "positions",
    "education.csv": "education",
    "skills.csv": "skills",
    "projects.csv": "projects",
    "certifications.csv": "certifications",
    "languages.csv": "languages",
    "honors.csv": "honors",
    "email addresses.csv": "emails",
}

UNSAFE = "That ZIP file looks unsafe or corrupted, so it wasn't read."
NONE_FOUND = (
    "No LinkedIn profile files found in that ZIP. Request the export with Profile, "
    "Positions, Education and Skills ticked, then upload the ZIP LinkedIn emails you."
)

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}


# --- zip ---------------------------------------------------------------------------------


def _unsafe_name(name: str) -> bool:
    n = name.replace("\\", "/")
    return (
        n.startswith("/")
        or re.match(r"^[A-Za-z]:", n) is not None
        or any(part == ".." for part in n.split("/"))
        or "\x00" in n
    )


def open_zip(data: bytes) -> tuple[zipfile.ZipFile, dict[str, zipfile.ZipInfo]]:
    """The archive and its allow-listed entries (file key -> info). Raises ZIP_UNSAFE."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        infos = z.infolist()
    except (zipfile.BadZipFile, ValueError, OSError):
        raise ImportFailure("ZIP_UNSAFE", UNSAFE) from None
    if len(infos) > MAX_ENTRIES:
        raise ImportFailure("ZIP_UNSAFE", UNSAFE)
    total = 0
    found: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        if _unsafe_name(info.filename):
            raise ImportFailure("ZIP_UNSAFE", UNSAFE)
        total += info.file_size
        if total > MAX_TOTAL:
            raise ImportFailure("ZIP_UNSAFE", UNSAFE)
        if info.file_size > RATIO_MIN_SIZE and info.file_size > MAX_RATIO * max(
            info.compress_size, 1
        ):
            raise ImportFailure("ZIP_UNSAFE", UNSAFE)
        if info.is_dir():
            continue
        base = info.filename.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
        key = ALLOWED.get(base)
        if key and key not in found:  # first at any depth wins
            found[key] = info
    return z, found


def _read(z: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    if info.file_size > MAX_CSV:
        raise ImportFailure("ZIP_UNSAFE", UNSAFE)
    try:
        with z.open(info) as f:
            raw = f.read(MAX_CSV + 1)  # never trust the declared size alone
    except (zipfile.BadZipFile, RuntimeError, OSError, NotImplementedError):
        raise ImportFailure("ZIP_UNSAFE", UNSAFE) from None
    if len(raw) > MAX_CSV:
        raise ImportFailure("ZIP_UNSAFE", UNSAFE)
    return raw.decode("utf-8-sig", errors="replace")


# --- csv ---------------------------------------------------------------------------------


def _hkey(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", h.lower())


def rows(text: str, expected: set[str]) -> list[dict[str, str]]:
    """CSV rows keyed by normalised header. Skips LinkedIn's "Notes:" preamble: the
    header is the first line naming at least one expected column."""
    lines = text.splitlines()
    start = 0
    for i, line in enumerate(lines):
        try:
            cells = next(csv.reader([line]))
        except (csv.Error, StopIteration):
            continue
        if {_hkey(c) for c in cells} & expected:
            start = i
            break
    else:
        return []
    reader = csv.reader(io.StringIO("\n".join(lines[start:])))
    try:
        header = [_hkey(h) for h in next(reader)]
    except StopIteration:
        return []
    out = []
    for r in reader:
        if not any(c.strip() for c in r):
            continue
        out.append({h: (r[i].strip() if i < len(r) else "") for i, h in enumerate(header)})
    return out


def _get(row: dict, *names: str) -> str:
    for n in names:
        v = row.get(_hkey(n), "")
        if v:
            return v
    return ""


# --- dates -------------------------------------------------------------------------------


def parse_date(raw: str) -> tuple[str | None, bool]:
    """LinkedIn date -> (YYYY-MM or None, approximate). Year only -> YYYY-01, approximate."""
    s = (raw or "").strip().lower().replace(",", " ")
    if not s:
        return None, False
    m = re.fullmatch(r"([a-z]+)\.?\s+(\d{4})", s)  # "Jan 2020", "January 2020"
    if m and m.group(1)[:3] in _MONTHS:
        return f"{m.group(2)}-{_MONTHS[m.group(1)[:3]]:02d}", False
    m = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-\d{1,2})?", s)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}", False
    m = re.fullmatch(r"(\d{1,2})/(\d{4})", s)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{m.group(2)}-{int(m.group(1)):02d}", False
    m = re.fullmatch(r"\d{1,2}\s+([a-z]+)\s+(\d{4})", s)  # "15 Jan 2020"
    if m and m.group(1)[:3] in _MONTHS:
        return f"{m.group(2)}-{_MONTHS[m.group(1)[:3]]:02d}", False
    m = re.fullmatch(r"(\d{4})", s)
    if m:
        return f"{m.group(1)}-01", True
    return None, False


def _dated(item_data: dict, start_raw: str, end_raw: str) -> list[str]:
    """Sets start_month / end_month; returns review notes for approximate dates."""
    notes = []
    start, approx_s = parse_date(start_raw)
    end, approx_e = parse_date(end_raw)  # empty Finished On = current role
    if start:
        item_data["start_month"] = start
    elif start_raw:
        notes.append(f"couldn't read the date “{start_raw}”")
    if end:
        item_data["end_month"] = end
    elif end_raw:
        notes.append(f"couldn't read the date “{end_raw}”")
    if approx_s or approx_e:
        notes.append("only the year is known; check the month")
    return notes


def _item(data: dict, notes: list[str], **kw) -> Item:
    item = Item(data={k: v for k, v in data.items() if v not in ("", None, [])}, **kw)
    if notes:
        item.needs_review = True
        reason = "; ".join(notes)
        item.reason = reason[:1].upper() + reason[1:]
    return item


# --- mapping -----------------------------------------------------------------------------

H = {
    "profile": {"firstname", "lastname", "headline", "summary", "geolocation"},
    "positions": {"companyname", "title", "startedon"},
    "education": {"schoolname", "degreename", "startdate"},
    "skills": {"name"},
    "projects": {"title", "description", "startedon"},
    "certifications": {"name", "authority"},
    "languages": {"name", "proficiency"},
    "honors": {"title", "issuedon"},
    "emails": {"emailaddress", "primary"},
}


def _profile(rs, ex: Extracted):
    if not rs:
        return
    r = rs[0]
    name = " ".join(x for x in (_get(r, "First Name"), _get(r, "Last Name")) if x)
    # Never Birth Date, Address, Zip Code, Maiden Name, Instant Messengers.
    for field, value in (
        ("full_name", name),
        ("headline", _get(r, "Headline")),
        ("summary", _get(r, "Summary")),
        ("location", _get(r, "Geo Location", "Location")),
    ):
        if value:
            ex.identity[field] = value


def _positions(rs, ex: Extracted):
    out = ex.sections.setdefault("experiences", [])
    for r in rs:
        data = {
            "company": _get(r, "Company Name", "Company"),
            "title": _get(r, "Title"),
            "location": _get(r, "Location"),
            "description": _get(r, "Description"),
        }
        notes = _dated(
            data, _get(r, "Started On", "Start Date"), _get(r, "Finished On", "End Date")
        )
        if data["company"] or data["title"]:
            out.append(_item(data, notes))


def _education(rs, ex: Extracted):
    out = ex.sections.setdefault("educations", [])
    for r in rs:
        degree = _get(r, "Degree Name", "Degree")
        data = {"institution": _get(r, "School Name", "School"), "degree": degree}
        field = None
        if degree and "," in degree:  # "B.Tech, Computer Science"
            head, tail = (p.strip() for p in degree.split(",", 1))
            if head and tail:
                data["degree"], field = head, tail
        data["field"] = field
        data["description"] = _get(r, "Notes") or None
        notes = _dated(
            data, _get(r, "Start Date", "Started On"), _get(r, "End Date", "Finished On")
        )
        if data["institution"]:
            out.append(_item(data, notes))


def _skills(rs, ex: Extracted, category: str | None = None, notes_col: str | None = None):
    out = ex.sections.setdefault("skills", [])
    for r in rs:
        name = _get(r, "Name", "Skill")
        if not name:
            continue
        data = {"name": name, "category": category}
        if notes_col and _get(r, notes_col):
            data["notes"] = _get(r, notes_col)
        out.append(_item(data, []))


def _projects(rs, ex: Extracted):
    out = ex.sections.setdefault("projects", [])
    for r in rs:
        url = _get(r, "Url", "URL")
        data = {
            "name": _get(r, "Title", "Name"),
            "summary": _get(r, "Description"),
            "live_url": url if re.match(r"^https?://", url, re.IGNORECASE) else None,
        }
        notes = _dated(data, _get(r, "Started On"), _get(r, "Finished On"))
        if not data["summary"]:
            notes.append("add a one-line summary")
        if data["name"]:
            out.append(_item(data, notes))


def _certifications(rs, ex: Extracted):
    out = ex.sections.setdefault("educations", [])
    for r in rs:
        data = {
            "institution": _get(r, "Authority") or _get(r, "Name"),
            "degree": _get(r, "Name"),
        }
        notes = _dated(data, _get(r, "Started On"), _get(r, "Finished On"))
        if "start_month" not in data:
            notes.append("add the month you earned it")
        if data["degree"]:
            out.append(_item(data, notes, kind="certification"))


def _honors(rs, ex: Extracted):
    lines = []
    for r in rs:
        title = _get(r, "Title")
        if not title:
            continue
        when = _get(r, "Issued On")
        desc = _get(r, "Description")
        line = "- " + title + (f" ({when})" if when else "") + (f": {desc}" if desc else "")
        lines.append(line)
    if lines:
        content = "Honors & awards:\n" + "\n".join(lines)
        ex.sections.setdefault("notes", []).append(_item({"content": content}, []))


def _emails(rs, ex: Extracted):
    out = ex.sections.setdefault("links", [])
    addrs = [
        (_get(r, "Email Address"), _get(r, "Primary").lower() in ("yes", "true", "1"))
        for r in rs
        if "@" in _get(r, "Email Address")
    ]
    many = len(addrs) > 1
    for addr, primary in addrs:
        # Several addresses: only the primary starts ticked.
        out.append(_item({"kind": "email", "value": addr}, [], default_skip=many and not primary))


MAPPERS = {
    "profile": _profile,
    "positions": _positions,
    "education": _education,
    "skills": _skills,
    "projects": _projects,
    "certifications": _certifications,
    "languages": lambda rs, ex: _skills(rs, ex, "language", "Proficiency"),
    "honors": _honors,
    "emails": _emails,
}
ORDER = list(ALLOWED.values())


def parse(data: bytes) -> Extracted:
    z, found = open_zip(data)
    if not found:
        raise ImportFailure("NO_LINKEDIN_FILES", NONE_FOUND)
    ex = Extracted()
    with z:
        for key in ORDER:
            if key in found:
                MAPPERS[key](rows(_read(z, found[key]), H[key]), ex)
    ex.sections = {k: v for k, v in ex.sections.items() if v}
    if not ex.identity and not ex.sections:
        raise ImportFailure("NO_LINKEDIN_FILES", NONE_FOUND)
    return ex


async def run(data: bytes, ctx: RunContext) -> Extracted:
    return parse(data)


register("linkedin", run)
