from mebot.imports import draft
from mebot.imports.pipelines import Extracted, Item
from tests.conftest import csrf


def add(c, section, **body):
    r = c.post(f"/api/admin/profile/{section}", json=body, headers=csrf(c))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def build(app, ex):
    from mebot.repos import bots

    with app.state.session_factory() as db:
        return draft.build(db, bots.get_primary(db).id, ex)["sections"]


def test_experience_new_same_changed_with_month_tolerance(admin_client, app):
    eid = add(admin_client, "experiences", company="Acme Corp", title="Backend Engineer",
              start_month="2021-02", description="Payments")  # fmt: skip
    sec = build(
        app,
        Extracted(
            sections={
                "experiences": [
                    # same thing, start one month off, punctuation/case differences
                    Item(
                        data={
                            "company": "ACME corp.",
                            "title": "backend engineer",
                            "start_month": "2021-03",
                        }
                    ),  # fmt: skip
                    Item(
                        data={
                            "company": "Acme Corp",
                            "title": "Backend Engineer",
                            "start_month": "2021-02",
                            "description": "Payments and fraud",
                        }
                    ),  # fmt: skip
                    # three months off: a different stint
                    Item(
                        data={
                            "company": "Acme Corp",
                            "title": "Backend Engineer",
                            "start_month": "2021-05",
                        }
                    ),  # fmt: skip
                    Item(data={"company": "Globex", "title": "Intern", "start_month": "2019-06"}),
                ]
            }
        ),
    )["experiences"]
    first, changed, other, new = sec
    assert first["match"]["status"] == "changed"  # start_month differs (diff shows it)
    assert first["match"]["diff"] == {"start_month": {"from": "2021-02", "to": "2021-03"}}
    assert changed["match"] == {
        "status": "changed",
        "existing_id": eid,
        "diff": {"description": {"from": "Payments", "to": "Payments and fraud"}},
    }
    assert changed["default_action"] == "update"
    assert other["match"]["status"] == "new" and new["default_action"] == "add"


def test_same_defaults_to_skip_and_aliases(admin_client, app):
    add(admin_client, "skills", name="PostgreSQL")
    add(admin_client, "skills", name="JavaScript")
    sec = build(
        app,
        Extracted(
            sections={
                "skills": [
                    Item(data={"name": "postgres"}),
                    Item(data={"name": "JS"}),
                    Item(data={"name": "Rust"}),
                ]
            }
        ),
    )["skills"]
    assert [(s["match"]["status"], s["default_action"]) for s in sec] == [
        ("same", "skip"),
        ("same", "skip"),
        ("new", "add"),
    ]


def test_education_project_link_matching(admin_client, app):
    add(
        admin_client, "educations", institution="IIT Bombay", degree="B.Tech", start_month="2016-07"
    )
    add(admin_client, "projects", name="mebot", summary="Portfolio bot")
    add(admin_client, "links", kind="email", value="jane@home.dev")
    sec = build(
        app,
        Extracted(
            sections={
                "educations": [
                    Item(
                        data={
                            "institution": "iit bombay",
                            "degree": "B.Tech",
                            "start_month": "2016-07",
                        }
                    )
                ],  # fmt: skip
                "projects": [Item(data={"name": "MeBot", "summary": "Portfolio bot"})],
                "links": [
                    Item(data={"kind": "email", "value": "Jane@Home.dev"}),
                    Item(data={"kind": "email", "value": "jane@work.dev"}),
                ],
            }
        ),
    )
    assert sec["educations"][0]["match"]["status"] == "same"
    assert sec["projects"][0]["match"]["status"] == "same"
    assert [x["match"]["status"] for x in sec["links"]] == ["same", "new"]


def test_identity_field_by_field(admin_client, app):
    r = admin_client.put(
        "/api/admin/profile/identity",
        json={"full_name": "Jane Doe", "headline": "Engineer"},
        headers=csrf(admin_client),
    )
    assert r.status_code == 200, r.text
    sec = build(
        app,
        Extracted(
            identity={"full_name": "Jane Doe", "headline": "Backend Engineer", "location": "Pune"}
        ),
    )["identity"]
    got = {i["data"]["field"]: (i["match"]["status"], i["default_action"]) for i in sec}
    assert got == {
        "full_name": ("same", "skip"),
        "headline": ("changed", "update"),
        "location": ("new", "add"),
    }
    headline = [i for i in sec if i["temp_id"] == "i-headline"][0]
    assert headline["match"]["diff"] == {"value": {"from": "Engineer", "to": "Backend Engineer"}}


def test_needs_review_and_invalid_default_to_skip(admin_client, app):
    sec = build(
        app,
        Extracted(
            sections={
                "experiences": [
                    Item(
                        data={"company": "Initech", "title": "Eng", "start_month": "2020-01"},
                        needs_review=True,
                        reason="“Initech” isn't in your resume",
                    ),  # fmt: skip
                    Item(data={"company": "Acme", "title": "Eng"}),  # no start month
                    Item(
                        data={
                            "company": "Acme",
                            "title": "Eng",
                            "start_month": "2022-01",
                            "end_month": "2021-01",
                        }
                    ),  # fmt: skip
                ],
                "links": [Item(data={"kind": "email", "value": "a@b.dev"}, default_skip=True)],
            }
        ),
    )
    a, b, c = sec["experiences"]
    assert a["needs_review"] and a["default_action"] == "skip" and "Initech" in a["reason"]
    assert b["needs_review"] and "start_month" in b["reason"] and b["default_action"] == "skip"
    assert c["needs_review"] and "before start" in c["reason"]
    assert sec["links"][0]["default_action"] == "skip" and not sec["links"][0]["needs_review"]


def test_notes_same_when_already_present(admin_client, app):
    admin_client.put("/api/admin/profile/notes", json={"content": "Honors & awards:\n- X"},
                     headers=csrf(admin_client))  # fmt: skip
    sec = build(
        app, Extracted(sections={"notes": [Item(data={"content": "Honors & awards:\n- X"})]})
    )
    assert sec["notes"][0]["match"]["status"] == "same"
