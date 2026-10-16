from mebot.imports import grounding
from mebot.imports.pipelines import Extracted, Item

SOURCE = """Jane Doe
Senior Backend Engineer, Bengaluru
Experience
Acme Corporation — Backend Engineer, Feb 2021 – Present
Built payment APIs.
Education
Indian Institute of Technology Bombay, B.Tech in Computer Science, 2016 – 2020
Skills: Python, FastAPI, PostgreSQL
Projects: mebot (github.com/jane/mebot)
"""


def run(sections=None, identity=None):
    ex = Extracted(identity=identity or {}, sections=sections or {})
    return grounding.review(ex, SOURCE)


def test_grounded_items_pass_with_snippet():
    ex = run(
        {
            "experiences": [
                Item(
                    data={
                        "company": "Acme Corporation",
                        "title": "Backend Engineer",
                        "start_month": "2021-02",
                    }
                )  # fmt: skip
            ],
            "skills": [Item(data={"name": "postgresql"})],
            "links": [Item(data={"kind": "github", "value": "https://github.com/jane/mebot"})],
        }
    )
    exp = ex.sections["experiences"][0]
    assert not exp.needs_review and exp.snippet.startswith("Acme Corporation")
    assert not ex.sections["skills"][0].needs_review
    assert not ex.sections["links"][0].needs_review


def test_fuzzy_match_tolerates_small_differences():
    ex = run(
        {"experiences": [Item(data={"company": "Acme Corporaton", "title": "Backend Engineer"})]}
    )
    assert not ex.sections["experiences"][0].needs_review


def test_invented_company_and_year_flagged():
    ex = run(
        {
            "experiences": [
                Item(
                    data={
                        "company": "Initech",
                        "title": "Backend Engineer",
                        "start_month": "2018-03",
                    }
                )
            ],
            "skills": [Item(data={"name": "Haskell"})],
        }
    )
    item = ex.sections["experiences"][0]
    assert item.needs_review and "Initech" in item.reason and "2018" in item.reason
    assert ex.sections["skills"][0].needs_review


def test_personal_data_and_phones_stripped():
    ex = run(
        {
            "experiences": [
                Item(
                    data={
                        "company": "Acme Corporation",
                        "title": "Backend Engineer",
                        "description": "Built payment APIs. Married with two kids. Call +91 98765 43210.",
                        "highlights": ["Led a team of 4", "Date of birth: 1 Jan 1995"],
                    }
                )
            ],
            "interests": [
                Item(data={"name": "Temple volunteering", "kind": "hobby"}),
                Item(data={"name": "Chess", "kind": "hobby"}),
            ],  # fmt: skip
            "links": [Item(data={"kind": "phone", "value": "+91 98765 43210"})],
        },
        identity={
            "full_name": "Jane Doe",
            "summary": "Backend engineer. Born 01/01/1995, date of birth listed. Hindu.",
            "location": "Bengaluru",
        },
    )
    exp = ex.sections["experiences"][0].data
    assert exp["description"] == "Built payment APIs."
    assert exp["highlights"] == ["Led a team of 4"]
    assert [i.data["name"] for i in ex.sections["interests"]] == ["Chess"]
    assert ex.sections["links"] == []
    assert ex.identity["summary"] == "Backend engineer."
    assert ex.identity["full_name"] == "Jane Doe"


def test_name_not_in_resume_is_dropped():
    ex = run(identity={"full_name": "Someone Else", "headline": "Engineer"})
    assert "full_name" not in ex.identity and ex.identity["headline"] == "Engineer"
