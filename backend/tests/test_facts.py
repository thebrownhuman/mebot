from datetime import date

import pytest

from mebot.profile.data import ProfileData
from mebot.profile.facts import (
    compute_facts,
    format_duration,
    month_span,
    normalize_skill,
    union_months,
)

AS_OF = date(2026, 10, 16)  # frozen: month index 2026-10


def exp(company, start, end=None, title="Engineer", kind=None, tech=()):
    return {
        "company": company,
        "title": title,
        "employment_type": kind,
        "start_month": start,
        "end_month": end,
        "tech": list(tech),
        "highlights": [],
    }


def profile(experiences=(), projects=(), skills=(), educations=(), identity=None):
    return ProfileData(
        identity=identity or {},
        sections={
            "experiences": list(experiences),
            "projects": list(projects),
            "skills": list(skills),
            "educations": list(educations),
        },
    )


# --- month math & formatting ---------------------------------------------------------


def test_inclusive_months():
    assert month_span("2022-01", "2022-12", AS_OF) == ("2022-01", "2022-12", 12)
    assert month_span("2022-01", "2022-01", AS_OF)[2] == 1
    assert month_span("2026-01", None, AS_OF) == ("2026-01", "2026-10", 10)  # current
    assert month_span("2027-01", None, AS_OF) is None  # future start
    assert month_span("2026-05", "2027-03", AS_OF) == ("2026-05", "2026-10", 6)  # capped
    assert month_span("2022-05", "2022-01", AS_OF) is None  # inverted


def test_union_merges_overlaps():
    spans = [month_span("2022-01", "2023-06", AS_OF), month_span("2023-01", "2024-01", AS_OF)]
    assert union_months(spans) == 25  # not 31
    adjacent = [month_span("2022-01", "2022-06", AS_OF), month_span("2022-07", "2022-12", AS_OF)]
    assert union_months(adjacent) == 12


@pytest.mark.parametrize(
    "months,text",
    [
        (0, "less than 1 month"),
        (1, "1 month"),
        (11, "11 months"),
        (12, "1 year"),
        (13, "1 year 1 month"),
        (24, "2 years"),
        (40, "3 years 4 months"),
    ],
)
def test_format_duration(months, text):
    assert format_duration(months) == text


@pytest.mark.parametrize(
    "raw,norm",
    [
        ("JS", "javascript"),
        ("TS", "typescript"),
        ("Postgres", "postgresql"),
        ("k8s", "kubernetes"),
        ("Golang", "go"),
        ("node", "node.js"),
        ("NodeJS", "node.js"),
        ("React.js", "react"),
        (" Python ", "python"),
    ],
)
def test_skill_aliases(raw, norm):
    assert normalize_skill(raw) == norm


# --- total experience ------------------------------------------------------------------


def test_total_experience_overlap_and_current():
    f = compute_facts(
        profile([exp("A", "2022-01", "2023-06"), exp("B", "2023-01", "2024-01")]), AS_OF
    )
    assert f["total_experience"]["months"] == 25
    assert f["total_experience"]["text"] == "2 years 1 month"
    assert f["total_experience"]["years"] == 2.1
    assert (f["total_experience"]["from"], f["total_experience"]["to"]) == ("2022-01", "2024-01")

    f = compute_facts(profile([exp("Acme", "2023-06")]), AS_OF)
    assert f["total_experience"]["months"] == 41  # 2023-06..2026-10 inclusive
    assert f["total_experience"]["to"] == "2026-10"
    assert f["as_of"] == "2026-10-16"


def test_current_month_moves_with_as_of():
    p = profile([exp("Acme", "2026-01")])
    assert compute_facts(p, date(2026, 10, 1))["total_experience"]["months"] == 10
    assert compute_facts(p, date(2026, 11, 1))["total_experience"]["months"] == 11


def test_no_experiences_means_no_total():
    f = compute_facts(profile(), AS_OF)
    assert f["total_experience"] is None and f["current_roles"] == []


def test_internships_excluded_by_default_and_toggle():
    p = profile(
        [
            exp("Uni Lab", "2021-01", "2021-06", kind="internship"),
            exp("Acme", "2022-01", "2022-12", kind="full-time"),
        ]
    )
    f = compute_facts(p, AS_OF)
    assert f["total_experience"]["months"] == 12
    assert f["total_experience"]["internships_counted"] is False
    assert f["internship_months"] == 6
    p.identity["count_internships"] = True
    assert compute_facts(p, AS_OF)["total_experience"]["months"] == 18


def test_only_internships():
    f = compute_facts(profile([exp("Lab", "2025-01", "2025-06", kind="internship")]), AS_OF)
    assert f["total_experience"]["months"] == 0
    assert f["internship_months"] == 6


def test_freelance_toggle():
    p = profile(
        [
            exp("Self", "2020-01", "2020-12", kind="freelance"),
            exp("Client", "2021-01", "2021-03", kind="contract"),
            exp("Acme", "2022-01", "2022-12"),
        ]
    )
    assert compute_facts(p, AS_OF)["total_experience"]["months"] == 27
    p.identity["count_freelance"] = False
    assert compute_facts(p, AS_OF)["total_experience"]["months"] == 12


def test_current_and_upcoming_roles_companies_first_start_gaps():
    p = profile(
        [
            exp("Old", "2019-01", "2019-12", title="Junior"),
            exp("Acme", "2024-02", None, title="Backend Engineer"),
            exp("Acme", "2023-01", "2024-01", title="Intern-to-hire"),
            exp("Next", "2027-02", None, title="Lead"),
        ]
    )
    f = compute_facts(p, AS_OF)
    assert f["current_roles"] == [
        {
            "company": "Acme",
            "title": "Backend Engineer",
            "since": "2024-02",
            "months": 33,
            "text": "2 years 9 months",
        }
    ]
    assert f["upcoming_roles"] == [{"company": "Next", "title": "Lead", "starts": "2027-02"}]
    acme = next(c for c in f["companies"] if c["company"] == "Acme")
    assert acme["months"] == 46  # 2023-01..2026-10
    assert f["first_job_start"] == "2019-01"
    assert f["gaps"] == [{"from": "2020-01", "to": "2022-12", "months": 36}]
    assert f["counts"]["companies"] == 2  # upcoming not counted


def test_not_currently_employed():
    f = compute_facts(profile([exp("Old", "2020-01", "2025-03")]), AS_OF)
    assert f["current_roles"] == [] and f["last_role_end"] == "2025-03"


# --- skills -----------------------------------------------------------------------------


def test_skill_years_from_experience_and_projects_with_aliases():
    p = profile(
        experiences=[exp("A", "2022-01", "2022-12", tech=["Python", "Postgres"])],
        projects=[
            {
                "name": "x",
                "tech": ["python"],
                "start_month": "2022-06",
                "end_month": "2023-06",
                "status": "completed",
            },
            {
                "name": "y",
                "tech": ["PostgreSQL"],
                "start_month": None,
                "end_month": None,
                "status": None,
            },
        ],
        skills=[
            {"name": "Python", "years_override": None},
            {"name": "PostgreSQL"},
            {"name": "Rust"},
        ],
    )
    skills = {s["name"]: s for s in compute_facts(p, AS_OF)["skills"]}
    assert skills["Python"]["months"] == 18  # 2022-01..2023-06 merged
    assert skills["Python"]["source"] == "computed"
    assert skills["Python"]["evidence"] == ["work", "projects"]
    assert skills["PostgreSQL"]["months"] == 12  # undated project adds nothing
    assert skills["Rust"]["months"] is None and skills["Rust"]["text"] is None


def test_skill_override_wins():
    p = profile(
        experiences=[exp("A", "2022-01", "2022-12", tech=["go"])],
        skills=[{"name": "Golang", "years_override": 5.5}],
    )
    s = compute_facts(p, AS_OF)["skills"][0]
    assert s == {
        "name": "Golang",
        "months": 66,
        "text": "5 years 6 months",
        "years": 5.5,
        "source": "stated",
        "evidence": [],
    }


# --- education & counts --------------------------------------------------------------------


def test_education_latest_and_in_progress():
    p = profile(
        educations=[
            {
                "degree": "BSc",
                "field": "CS",
                "institution": "Uni",
                "start_month": "2015-09",
                "end_month": "2019-06",
            },
            {
                "degree": "MSc",
                "field": None,
                "institution": "Tech",
                "start_month": "2025-09",
                "end_month": None,
            },
        ]
    )
    edu = compute_facts(p, AS_OF)["education"]["latest"]
    assert edu == {
        "degree": "MSc",
        "field": None,
        "institution": "Tech",
        "end_month": None,
        "in_progress": True,
    }
    p.sections["educations"].pop()
    edu = compute_facts(p, AS_OF)["education"]["latest"]
    assert edu["degree"] == "BSc" and edu["in_progress"] is False


def test_counts_projects_by_status():
    p = profile(
        projects=[
            {"name": "a", "status": "completed", "tech": []},
            {"name": "b", "status": "active", "tech": []},
            {"name": "c", "status": None, "tech": []},
        ]
    )
    c = compute_facts(p, AS_OF)["counts"]
    assert c["projects"] == 3
    assert c["projects_by_status"] == {"completed": 1, "active": 1, "unspecified": 1}
