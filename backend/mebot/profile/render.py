"""Structured profile -> the knowledge block used by the chat prompt and the preview.

Feature 5 extends this (computed facts, stricter grounding): keep it a pure function
of ProfileData so it can be tested and previewed without a request.
"""

from mebot.profile.data import ProfileData


def _period(start: str | None, end: str | None) -> str:
    if not start and not end:
        return ""
    return f"{start or '?'} to {end or 'present'}"


def _join(*parts) -> str:
    return ", ".join(p for p in parts if p)


def _line(label: str, value) -> str | None:
    if value is None or value == "" or value == []:
        return None
    if isinstance(value, list):
        value = "; ".join(value)
    return f"{label}: {value}"


def _block(title: str, lines: list[str | None]) -> str | None:
    body = [ln for ln in lines if ln]
    # Clear delimiters: owner data is rendered as data inside labelled sections.
    return f"=== {title} ===\n" + "\n".join(body) if body else None


def _indent(lines: list[str | None]) -> list[str]:
    return ["  " + ln for ln in lines if ln]


def _identity(p: ProfileData) -> str | None:
    i = p.identity
    lines = [
        _line("Name", i.get("full_name")),
        _line("Headline", i.get("headline")),
        _line("Location", i.get("location")),
        _line("Open to", i.get("open_to")),
        _line("Summary", i.get("summary")),
        _line("Public email", i.get("email_public")),
        _line("Public phone", i.get("phone_public")),
        _line("Notice period", i.get("notice_period")),
        _line("Salary expectation", i.get("salary_expectation")),
        _line("Work authorisation", i.get("work_authorization")),
    ]
    lines += [f"Link ({link['label']}): {link['url']}" for link in p.items("links")]
    return _block("IDENTITY", lines)


def _experience(p: ProfileData) -> str | None:
    lines: list[str | None] = []
    for e in p.items("experiences"):
        meta = _join(e.get("employment_type"), e.get("location"))
        head = f"- {e['title']} at {e['company']}" + (f" ({meta})" if meta else "")
        lines.append(f"{head}, {_period(e['start_month'], e.get('end_month'))}")
        lines += _indent(
            [e.get("description"), _line("Highlights", e["highlights"]), _line("Tech", e["tech"])]
        )
    return _block("EXPERIENCE", lines)


def _education(p: ProfileData) -> str | None:
    lines: list[str | None] = []
    for e in p.items("educations"):
        degree = e["degree"] + (f" in {e['field']}" if e.get("field") else "")
        period = _period(e["start_month"], e.get("end_month"))
        lines.append(f"- {degree}, {e['institution']}, {period}")
        lines += _indent([_line("Grade", e.get("grade")), e.get("description")])
    return _block("EDUCATION", lines)


def _skills(p: ProfileData) -> str | None:
    lines = []
    for s in p.items("skills"):
        years = s.get("years_override")
        meta = _join(s.get("category"), s.get("level"), f"{years:g} years" if years else None)
        line = f"- {s['name']}" + (f" ({meta})" if meta else "")
        lines.append(line + (f": {s['notes']}" if s.get("notes") else ""))
    return _block("SKILLS", lines)


def _projects(p: ProfileData) -> str | None:
    lines: list[str | None] = []
    for pr in p.items("projects"):
        lines.append(f"- {pr['name']}" + (f": {pr['tagline']}" if pr.get("tagline") else ""))
        lines += _indent(
            [
                _line("Summary", pr.get("summary")),
                _line("Problem", pr.get("problem")),
                _line("My role", pr.get("my_role")),
                _line("Frontend", pr.get("frontend")),
                _line("Backend", pr.get("backend")),
                _line("Infrastructure", pr.get("infra")),
                _line("Data / AI", pr.get("data_ai")),
                _line("Highlights", pr["highlights"]),
                _line("Tech", pr["tech"]),
                _line("Repository", pr.get("repo_url")),
                _line("Live", pr.get("live_url")),
                _line("Period", _period(pr.get("start_month"), pr.get("end_month"))),
                _line("Status", pr.get("status")),
            ]
        )
    return _block("PROJECTS", lines)


def _interests(p: ProfileData) -> str | None:
    lines = [
        f"- {i['kind'].capitalize()}: {i['name']}"
        + (f" ({i['description']})" if i.get("description") else "")
        for i in p.items("interests")
    ]
    return _block("INTERESTS & HOBBIES", lines)


def _faq(p: ProfileData) -> str | None:
    return _block("FAQ", [f"Q: {f['question']}\nA: {f['answer']}" for f in p.items("faqs")])


def _avoid(p: ProfileData) -> str | None:
    lines = [
        f"- {a['topic']}" + (f' (reply: "{a["reply"]}")' if a.get("reply") else "")
        for a in p.items("avoid-topics")
    ]
    return _block("AVOID", lines)


def _notes(p: ProfileData) -> str | None:
    return _block("NOTES", [p.notes.strip()]) if p.notes.strip() else None


def render_profile(profile: ProfileData) -> str:
    """Labelled sections; empty sections are omitted."""
    blocks = [
        _identity(profile),
        _experience(profile),
        _education(profile),
        _skills(profile),
        _projects(profile),
        _interests(profile),
        _faq(profile),
        _avoid(profile),
        _notes(profile),
    ]
    return "\n\n".join(b for b in blocks if b)


def approx_tokens(text: str) -> int:
    """Rough estimate (~4 chars/token) for size warnings, not billing."""
    return (len(text) + 3) // 4
