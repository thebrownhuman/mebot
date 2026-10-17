"""Structured profile -> the knowledge block used by the chat prompt and the preview.

Feature 5 extends this (computed facts, stricter grounding): keep it a pure function
of ProfileData so it can be tested and previewed without a request.
"""

from datetime import date

from mebot import channels
from mebot.marker import neutralise
from mebot.persona import display_name
from mebot.profile.data import ProfileData
from mebot.profile.facts import compute_facts, format_duration, today_utc


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
        _line("Pronouns", i.get("pronouns")),
        _line("Headline", i.get("headline")),
        _line("Location", i.get("location")),
        _line("Open to", i.get("open_to")),
        _line("Summary", i.get("summary")),
        _line("Notice period", i.get("notice_period")),
        _line("Salary expectation", i.get("salary_expectation")),
        _line("Work authorisation", i.get("work_authorization")),
    ]
    return _block("IDENTITY", lines)


def _contact(p: ProfileData) -> str | None:
    """Shared channels only: a non-shared value must never reach the model."""
    lines = []
    for c in channels.from_items(p.items("links")):
        if not c.share:
            continue
        text = c.display if c.kind in ("email", "phone") else c.href or c.display
        if c.kind == "whatsapp":
            text = f"{c.display} ({c.href})"
        lines.append(f"- {c.label}: {text}")
    who = display_name(p.identity)
    return _block(
        f"CONTACT CHANNELS (share these when someone wants to reach or meet {who})", lines
    )


def experience_lines(e: dict) -> list[str | None]:
    meta = _join(e.get("employment_type"), e.get("location"))
    head = f"- {e['title']} at {e['company']}" + (f" ({meta})" if meta else "")
    return [
        f"{head}, {_period(e['start_month'], e.get('end_month'))}",
        *_indent(
            [e.get("description"), _line("Highlights", e["highlights"]), _line("Tech", e["tech"])]
        ),
    ]


def _experience(p: ProfileData) -> str | None:
    lines: list[str | None] = []
    for e in p.items("experiences"):
        lines += experience_lines(e)
    return _block("EXPERIENCE", lines)


def education_lines(e: dict) -> list[str | None]:
    degree = e["degree"] + (f" in {e['field']}" if e.get("field") else "")
    period = _period(e["start_month"], e.get("end_month"))
    return [
        f"- {degree}, {e['institution']}, {period}",
        *_indent([_line("Grade", e.get("grade")), e.get("description")]),
    ]


def _education(p: ProfileData) -> str | None:
    lines: list[str | None] = []
    for e in p.items("educations"):
        lines += education_lines(e)
    return _block("EDUCATION", lines)


def skill_line(s: dict) -> str:
    years = s.get("years_override")
    meta = _join(s.get("category"), s.get("level"), f"{years:g} years" if years else None)
    line = f"- {s['name']}" + (f" ({meta})" if meta else "")
    return line + (f": {s['notes']}" if s.get("notes") else "")


def _skills(p: ProfileData) -> str | None:
    return _block("SKILLS", [skill_line(s) for s in p.items("skills")])


def project_lines(pr: dict) -> list[str | None]:
    return [
        f"- {pr['name']}" + (f": {pr['tagline']}" if pr.get("tagline") else ""),
        *_indent(
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
        ),
    ]


def _projects(p: ProfileData) -> str | None:
    lines: list[str | None] = []
    for pr in p.items("projects"):
        lines += project_lines(pr)
    return _block("PROJECTS", lines)


def interest_line(i: dict) -> str:
    return f"- {i['kind'].capitalize()}: {i['name']}" + (
        f" ({i['description']})" if i.get("description") else ""
    )


def _interests(p: ProfileData) -> str | None:
    return _block("INTERESTS & HOBBIES", [interest_line(i) for i in p.items("interests")])


def faq_text(f: dict) -> str:
    return f"Q: {f['question']}\nA: {f['answer']}"


def _faq(p: ProfileData) -> str | None:
    return _block("FAQ", [faq_text(f) for f in p.items("faqs")])


def _learned(p: ProfileData) -> str | None:
    if not p.learned:
        return None
    who = display_name(p.identity)
    # Newest first; as authoritative as the rest of the profile (the owner approved each).
    return _block(f"LEARNED FACTS (confirmed by {who})", [f"- {t}" for t in p.learned])


def _avoid(p: ProfileData) -> str | None:
    lines = [
        f"- {a['topic']}" + (f' (reply: "{a["reply"]}")' if a.get("reply") else "")
        for a in p.items("avoid-topics")
    ]
    return _block("AVOID", lines)


def _notes(p: ProfileData) -> str | None:
    return _block("NOTES", [p.notes.strip()]) if p.notes.strip() else None


def _evidence(kinds: list[str]) -> str:
    return " and ".join(kinds)


def _total_lines(f: dict, who: str) -> list[str]:
    total = f["total_experience"]
    if total is None:
        return []
    interns = f["internship_months"]
    if total["months"] == 0:
        line = f"{who} has no full-time professional experience yet"
        return [line + (f"; {format_duration(interns)} of internships." if interns else ".")]
    scope = "internships included" if total["internships_counted"] else "internships excluded"
    if not total["freelance_counted"]:
        scope += ", freelance and contract work excluded"
    lines = [
        f"{who}'s total professional experience: {total['text']} "
        f"({total['years']:.1f} years), counted "
        f"from {total['from']} to {total['to']}, overlapping roles merged, {scope}."
    ]
    if interns and not total["internships_counted"]:
        lines.append(f"{who}'s internships (not counted above): {format_duration(interns)}.")
    return lines


def _education_line(f: dict, who: str) -> str | None:
    e = f["education"]["latest"]
    if not e:
        return None
    what = e["degree"] + (f" in {e['field']}" if e.get("field") else "") + f", {e['institution']}"
    if e["in_progress"]:
        when = f"in progress, expected {e['end_month']}" if e["end_month"] else "in progress"
    else:
        when = f"graduated {e['end_month']}"
    return f"{who}'s most recent education: {what} ({when})."


def render_facts(profile: ProfileData, as_of: date | None = None) -> str | None:
    """The authoritative FACTS block: plain sentences, numbers computed server-side."""
    f = compute_facts(profile, as_of)
    who = display_name(profile.identity)
    who = who[0].upper() + who[1:]  # "the candidate" starts a sentence
    lines: list[str | None] = list(_total_lines(f, who))
    lines += [
        f"{who}'s current role: {r['title']} at {r['company']} (since {r['since']}, {r['text']})."
        for r in f["current_roles"]
    ]
    if f["last_role_end"]:
        lines.append(
            f"{who} is not currently employed; most recent role ended {f['last_role_end']}."
        )
    lines += [
        f"{who}'s upcoming role: {r['title']} at {r['company']} (starting {r['starts']})."
        for r in f["upcoming_roles"]
    ]
    lines += [f"{who}'s time at {c['company']}: {c['text']}." for c in f["companies"]]
    if f["first_job_start"]:
        lines.append(f"{who}'s first professional role started: {f['first_job_start']}.")
    for s in f["skills"]:
        if s["source"] == "stated":
            lines.append(f"{who}'s {s['name']} experience: {s['text']} (stated by {who}).")
        elif s["source"] == "computed":
            lines.append(
                f"{who}'s {s['name']} experience: about {s['text']} "
                f"(from {_evidence(s['evidence'])})."
            )
    lines.append(_education_line(f, who))
    counts = f["counts"]
    if counts["projects"]:
        parts = [f"{n} {k}" for k, n in counts["projects_by_status"].items() if k != "unspecified"]
        n = counts["projects"]
        lines.append(
            f"{who} lists {n} project{'s' if n != 1 else ''}"
            + (f" ({', '.join(parts)})." if parts else ".")
        )
    if counts["companies"]:
        n = counts["companies"]
        lines.append(f"{who} has worked at {n} {'company' if n == 1 else 'companies'}.")
    body = [ln for ln in lines if ln]
    if not body:
        return None
    header = f"=== FACTS (computed by the system as of {f['as_of']} — authoritative) ==="
    return header + "\n" + "\n".join(body)


def render_profile(profile: ProfileData, as_of: date | None = None) -> str:
    """FACTS first, then labelled sections; empty sections are omitted."""
    as_of = as_of or today_utc()
    blocks = [
        render_facts(profile, as_of),
        _identity(profile),
        _contact(profile),
        _experience(profile),
        _education(profile),
        _skills(profile),
        _projects(profile),
        _interests(profile),
        _faq(profile),
        _learned(profile),
        _avoid(profile),
        _notes(profile),
    ]
    return neutralise("\n\n".join(b for b in blocks if b))


def approx_tokens(text: str) -> int:
    """Rough estimate (~4 chars/token) for size warnings, not billing."""
    return (len(text) + 3) // 4
