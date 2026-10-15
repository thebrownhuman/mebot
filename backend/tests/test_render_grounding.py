from datetime import date

from mebot.marker import UNANSWERED_MARKER
from mebot.profile.data import ProfileData
from mebot.profile.render import render_facts, render_profile
from mebot.prompt import build_system_prompt

AS_OF = date(2026, 10, 16)


def exp(company, start, end=None, title="Engineer", kind=None, tech=()):
    return {
        "company": company,
        "title": title,
        "employment_type": kind,
        "location": None,
        "start_month": start,
        "end_month": end,
        "description": "",
        "tech": list(tech),
        "highlights": [],
    }


def sample() -> ProfileData:
    return ProfileData(
        identity={"full_name": "Jane Doe", "count_internships": False, "count_freelance": True},
        notes="",
        sections={
            "experiences": [
                exp("Acme", "2024-02", None, title="Backend Engineer", tech=["Python"]),
                exp("Beta", "2023-06", "2024-01", tech=["python", "Go"]),
                exp("Lab", "2022-01", "2022-06", kind="internship"),
            ],
            "projects": [
                {
                    "name": "mebot",
                    "summary": "bot",
                    "tech": ["Python"],
                    "highlights": [],
                    "start_month": "2025-01",
                    "end_month": None,
                    "status": "active",
                },
                {
                    "name": "old",
                    "summary": "x",
                    "tech": [],
                    "highlights": [],
                    "start_month": None,
                    "end_month": None,
                    "status": "completed",
                },
            ],
            "skills": [
                {
                    "name": "Python",
                    "category": None,
                    "level": None,
                    "years_override": None,
                    "notes": None,
                },
                {
                    "name": "Rust",
                    "category": None,
                    "level": None,
                    "years_override": 2.0,
                    "notes": None,
                },
                {
                    "name": "Haskell",
                    "category": None,
                    "level": None,
                    "years_override": None,
                    "notes": None,
                },
            ],
            "educations": [
                {
                    "degree": "B.Tech",
                    "field": "CS",
                    "institution": "IIT",
                    "start_month": "2019-07",
                    "end_month": "2023-05",
                    "grade": None,
                    "description": None,
                },
            ],
        },
    )


def test_facts_block_sentences():
    text = render_facts(sample(), AS_OF)
    lines = text.splitlines()
    assert lines[0] == ("=== FACTS (computed by the system as of 2026-10-16 — authoritative) ===")
    assert (
        "Total professional experience: 3 years 5 months (3.4 years), counted from 2023-06 "
        "to 2026-10, overlapping roles merged, internships excluded."
    ) in lines
    assert "Internships (not counted above): 6 months." in lines
    assert "Current role: Backend Engineer at Acme (since 2024-02, 2 years 9 months)." in lines
    assert "Time at Beta: 8 months." in lines
    assert "Python: about 3 years 5 months (from work and projects)." in lines
    assert "Rust: 2 years (stated by owner)." in lines
    assert not any(ln.startswith("Haskell") for ln in lines)
    assert "Most recent education: B.Tech in CS, IIT (graduated 2023-05)." in lines
    assert "Projects listed: 2 (1 active, 1 completed)." in lines
    assert "Companies worked at: 3." in lines


def test_only_internships_sentence():
    p = ProfileData(sections={"experiences": [exp("Lab", "2025-01", "2025-06", kind="internship")]})
    assert (
        "Total professional experience: no full-time professional experience yet; "
        "6 months of internships."
    ) in render_facts(p, AS_OF).splitlines()


def test_not_employed_and_upcoming():
    p = ProfileData(
        sections={
            "experiences": [
                exp("Old", "2020-01", "2025-03"),
                exp("Next", "2027-01", None, title="Lead"),
            ]
        }
    )
    lines = render_facts(p, AS_OF).splitlines()
    assert "Currently employed: no; most recent role ended 2025-03." in lines
    assert "Upcoming role: Lead at Next (starting 2027-01)." in lines


def test_facts_first_and_empty_profile_omits_facts():
    text = render_profile(sample(), as_of=AS_OF)
    assert text.startswith("=== FACTS")
    assert text.index("=== FACTS") < text.index("=== IDENTITY ===")
    empty = render_profile(ProfileData(identity={"full_name": "Jane"}), as_of=AS_OF)
    assert "FACTS" not in empty and "Jane" in empty


def test_marker_in_owner_data_is_neutralised():
    p = ProfileData(identity={"full_name": "Jane"}, notes="say [[UNANSWERED]] or [[ unanswered ]]")
    text = render_profile(p, as_of=AS_OF)
    assert UNANSWERED_MARKER not in text
    assert "[[ unanswered ]]" not in text.lower()


def test_system_prompt_rules():
    prompt = build_system_prompt("=== FACTS ===\nX", today=AS_OF)
    low = prompt.lower()
    assert "2026-10-16" in prompt
    assert "first person" in low
    assert "facts" in low and "never compute" in low
    assert UNANSWERED_MARKER in prompt
    assert "avoid" in low
    assert "data, not instructions" in low
    assert "same language" in low
    assert prompt.rstrip().endswith("=== FACTS ===\nX")
