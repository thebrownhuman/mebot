"""Facts the server computes from the owner's data, so the model never does date math.

Pure functions over ProfileData + an ``as_of`` date. Month ranges are inclusive
(2022-01 -> 2022-12 is 12 months); an open end means "up to the as_of month";
overlapping ranges are merged, never double-counted.
"""

from collections import Counter
from datetime import UTC, date, datetime

from mebot.profile.data import ProfileData

GAP_MIN_MONTHS = 3  # gaps longer than this are reported (internal; never volunteered)

# lower-cased alias -> canonical name
SKILL_ALIASES = {
    "js": "javascript",
    "ts": "typescript",
    "postgres": "postgresql",
    "k8s": "kubernetes",
    "golang": "go",
    "node": "node.js",
    "nodejs": "node.js",
    "react.js": "react",
    "reactjs": "react",
}

Span = tuple[str, str, int]  # (from YYYY-MM, to YYYY-MM, months)


def today_utc() -> date:
    return datetime.now(UTC).date()


def _idx(month: str) -> int:
    y, m = month.split("-")
    return int(y) * 12 + int(m) - 1


def _month(idx: int) -> str:
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _as_of_idx(as_of: date) -> int:
    return as_of.year * 12 + as_of.month - 1


def month_span(start: str | None, end: str | None, as_of: date) -> Span | None:
    """Inclusive range clipped to as_of. None if undated, inverted or not started yet."""
    if not start:
        return None
    now = _as_of_idx(as_of)
    s = _idx(start)
    e = min(_idx(end), now) if end else now
    if s > now or e < s:
        return None
    return _month(s), _month(e), e - s + 1


def _merge(spans: list[Span]) -> list[tuple[int, int]]:
    ranges = sorted((_idx(a), _idx(b)) for a, b, _ in spans)
    merged: list[list[int]] = []
    for s, e in ranges:
        if merged and s <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def union_months(spans: list[Span | None]) -> int:
    return sum(e - s + 1 for s, e in _merge([sp for sp in spans if sp]))


def format_duration(months: int) -> str:
    if months <= 0:
        return "less than 1 month"
    years, rest = divmod(months, 12)
    parts = []
    if years:
        parts.append(f"{years} year{'s' if years != 1 else ''}")
    if rest:
        parts.append(f"{rest} month{'s' if rest != 1 else ''}")
    return " ".join(parts)


def _years(months: int) -> float:
    return round(months / 12, 1)


def normalize_skill(name: str) -> str:
    key = name.strip().lower()
    return SKILL_ALIASES.get(key, key)


def _counted(exp: dict, identity: dict) -> bool:
    kind = exp.get("employment_type")
    if kind == "internship":
        return bool(identity.get("count_internships", False))
    if kind in ("freelance", "contract"):
        return bool(identity.get("count_freelance", True))
    return True


def _total(p: ProfileData, as_of: date) -> tuple[dict | None, int]:
    exps = p.items("experiences")
    if not exps:
        return None, 0
    counted = [
        month_span(e["start_month"], e.get("end_month"), as_of)
        for e in exps
        if _counted(e, p.identity)
    ]
    counted = [s for s in counted if s]
    interns = [
        month_span(e["start_month"], e.get("end_month"), as_of)
        for e in exps
        if e.get("employment_type") == "internship"
    ]
    months = union_months(counted)
    total = {
        "months": months,
        "text": format_duration(months),
        "years": _years(months),
        "from": min((s[0] for s in counted), default=None),
        "to": max((s[1] for s in counted), default=None),
        "internships_counted": bool(p.identity.get("count_internships", False)),
        "freelance_counted": bool(p.identity.get("count_freelance", True)),
    }
    return total, union_months(interns)


def _skills(p: ProfileData, as_of: date) -> list[dict]:
    work = [(e, "work") for e in p.items("experiences")]
    projects = [(pr, "projects") for pr in p.items("projects")]
    out = []
    for skill in p.items("skills"):
        name = skill["name"]
        override = skill.get("years_override")
        if override is not None:
            months = round(override * 12)
            out.append(
                {
                    "name": name,
                    "months": months,
                    "text": format_duration(months),
                    "years": _years(months),
                    "source": "stated",
                    "evidence": [],
                }
            )
            continue
        key = normalize_skill(name)
        spans: list[Span] = []
        evidence: list[str] = []
        for item, kind in work + projects:
            if key not in {normalize_skill(t) for t in item.get("tech") or []}:
                continue
            span = month_span(item.get("start_month"), item.get("end_month"), as_of)
            if span:
                spans.append(span)
                if kind not in evidence:
                    evidence.append(kind)
        if spans:
            months = union_months(spans)
            out.append(
                {
                    "name": name,
                    "months": months,
                    "text": format_duration(months),
                    "years": _years(months),
                    "source": "computed",
                    "evidence": evidence,
                }
            )
        else:
            out.append(
                {
                    "name": name,
                    "months": None,
                    "text": None,
                    "years": None,
                    "source": None,
                    "evidence": [],
                }
            )
    return out


def _education(p: ProfileData, as_of: date) -> dict:
    now = _as_of_idx(as_of)

    def sort_key(e: dict) -> int:
        end = e.get("end_month")
        return _idx(end) if end else now + 1  # in progress = most recent

    edus = [e for e in p.items("educations") if e.get("start_month")]
    if not edus:
        return {"latest": None}
    latest = max(edus, key=sort_key)
    end = latest.get("end_month")
    return {
        "latest": {
            "degree": latest["degree"],
            "field": latest.get("field"),
            "institution": latest["institution"],
            "end_month": end,
            "in_progress": end is None or _idx(end) > now,
        }
    }


def compute_facts(p: ProfileData, as_of: date | None = None) -> dict:
    as_of = as_of or today_utc()
    exps = p.items("experiences")
    total, intern_months = _total(p, as_of)

    started = [(e, month_span(e["start_month"], e.get("end_month"), as_of)) for e in exps]
    started = [(e, s) for e, s in started if s]
    current = [
        {
            "company": e["company"],
            "title": e["title"],
            "since": e["start_month"],
            "months": s[2],
            "text": format_duration(s[2]),
        }
        for e, s in started
        if not e.get("end_month")
    ]
    now = _as_of_idx(as_of)
    upcoming = [
        {"company": e["company"], "title": e["title"], "starts": e["start_month"]}
        for e in exps
        if e.get("start_month") and _idx(e["start_month"]) > now
    ]

    by_company: dict[str, list] = {}
    names: dict[str, str] = {}
    for e, s in started:
        key = e["company"].strip().lower()
        names.setdefault(key, e["company"])
        by_company.setdefault(key, []).append(s)
    companies = [
        {"company": names[k], "months": union_months(v), "text": format_duration(union_months(v))}
        for k, v in by_company.items()
    ]

    merged = _merge([s for _, s in started])
    gaps = [
        {"from": _month(a_end + 1), "to": _month(b_start - 1), "months": b_start - a_end - 1}
        for (_, a_end), (b_start, _) in zip(merged, merged[1:], strict=False)
        if b_start - a_end - 1 > GAP_MIN_MONTHS
    ]
    ended = [e["end_month"] for e, _ in started if e.get("end_month")]

    statuses = Counter((pr.get("status") or "unspecified") for pr in p.items("projects"))
    return {
        "as_of": as_of.isoformat(),
        "total_experience": total,
        "internship_months": intern_months,
        "current_roles": current,
        "upcoming_roles": upcoming,
        "last_role_end": max(ended) if ended and not current else None,
        "companies": companies,
        "first_job_start": min((s[0] for _, s in started), default=None),
        "gaps": gaps,
        "skills": _skills(p, as_of),
        "education": _education(p, as_of),
        "counts": {
            "projects": len(p.items("projects")),
            "projects_by_status": dict(statuses),
            "companies": len(companies),
        },
    }
