import pytest

from mebot.imports.pipelines import Extracted, Item
from tests.conftest import csrf
from tests.import_fixtures import make_pdf


def add(c, section, **body):
    r = c.post(f"/api/admin/profile/{section}", json=body, headers=csrf(c))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def items(c, section):
    return c.get(f"/api/admin/profile/{section}").json()["items"]


@pytest.fixture
def make_job(admin_client, app):
    """Upload through the API with a runner that returns the given Extracted."""
    n = [0]

    def make(ex: Extracted):
        async def run(data, ctx):
            return ex

        app.state.import_runners = {"resume": run}
        n[0] += 1
        r = admin_client.post(
            "/api/admin/import/resume",
            files={"file": ("cv.pdf", make_pdf(["Resume", str(n[0])]))},
            headers=csrf(admin_client),
        )
        assert r.status_code == 202, r.text
        job = admin_client.get(f"/api/admin/import/jobs/{r.json()['id']}").json()
        assert job["status"] == "ready", job
        return job

    return make


def apply(c, job, decisions):
    return c.post(
        f"/api/admin/import/jobs/{job['id']}/apply",
        json={"decisions": decisions},
        headers=csrf(c),
    )


def defaults(job):
    return [
        {"temp_id": e["temp_id"], "action": e["default_action"]}
        for entries in job["draft"]["sections"].values()
        for e in entries
    ]


def test_apply_adds_updates_skips_with_counts(admin_client, make_job):
    eid = add(admin_client, "experiences", company="Acme", title="Engineer",
              start_month="2021-02", description="Old")  # fmt: skip
    add(admin_client, "skills", name="Python")
    job = make_job(
        Extracted(
            identity={"headline": "Backend Engineer", "location": "Pune"},
            sections={
                "experiences": [
                    Item(
                        data={
                            "company": "Acme",
                            "title": "Engineer",
                            "start_month": "2021-02",
                            "description": "New text",
                        }
                    ),  # fmt: skip
                    Item(
                        data={
                            "company": "Globex",
                            "title": "Intern",
                            "start_month": "2019-06",
                            "end_month": "2019-12",
                        }
                    ),  # fmt: skip
                ],
                "skills": [Item(data={"name": "python"}), Item(data={"name": "Go"})],
                "projects": [Item(data={"name": "mebot", "summary": "Bot"})],
            },
        )
    )
    r = apply(admin_client, job, defaults(job))
    assert r.status_code == 200, r.text
    assert r.json()["applied"] == {
        "identity": {"added": 0, "updated": 2},
        "experiences": {"added": 1, "updated": 1},
        "skills": {"added": 1, "updated": 0},
        "projects": {"added": 1, "updated": 0},
    }
    exps = {e["company"]: e for e in items(admin_client, "experiences")}
    assert exps["Acme"]["id"] == eid and exps["Acme"]["description"] == "New text"
    assert exps["Globex"]["end_month"] == "2019-12"
    assert sorted(s["name"] for s in items(admin_client, "skills")) == ["Go", "Python"]
    ident = admin_client.get("/api/admin/profile/identity").json()
    assert ident["headline"] == "Backend Engineer" and ident["location"] == "Pune"
    job_after = admin_client.get(f"/api/admin/import/jobs/{job['id']}").json()
    assert job_after["status"] == "applied" and job_after["draft"] is None
    assert job_after["applied_summary"]["skills"] == {"added": 1, "updated": 0}


def test_reapply_409(admin_client, make_job):
    job = make_job(Extracted(sections={"skills": [Item(data={"name": "Go"})]}))
    assert apply(admin_client, job, defaults(job)).status_code == 200
    r = apply(admin_client, job, defaults(job))
    assert r.status_code == 409 and r.json()["error"]["code"] == "ALREADY_APPLIED"


def test_one_invalid_edit_applies_nothing(admin_client, make_job):
    job = make_job(
        Extracted(
            sections={
                "skills": [Item(data={"name": "Go"})],
                "experiences": [
                    Item(data={"company": "Acme", "title": "Eng", "start_month": "2021-01"})
                ],
            }
        )
    )
    decisions = [
        {"temp_id": "s1", "action": "add"},
        {"temp_id": "e1", "action": "add", "data": {"company": "Acme", "title": "Eng",
                                                     "start_month": "2022-01",
                                                     "end_month": "2021-01"}},
    ]  # fmt: skip
    r = apply(admin_client, job, decisions)
    assert r.status_code == 422
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert "e1.end_month" in fields
    assert items(admin_client, "skills") == [] and items(admin_client, "experiences") == []
    assert admin_client.get(f"/api/admin/import/jobs/{job['id']}").json()["status"] == "ready"


def test_identity_only_fields_chosen(admin_client, make_job):
    admin_client.put(
        "/api/admin/profile/identity",
        json={"full_name": "Jane Doe", "headline": "Engineer", "summary": "Mine"},
        headers=csrf(admin_client),
    )
    job = make_job(Extracted(identity={"headline": "Backend Engineer", "summary": "Theirs"}))
    r = apply(admin_client, job, [{"temp_id": "i-headline", "action": "update"},
                                   {"temp_id": "i-summary", "action": "skip"}])  # fmt: skip
    assert r.status_code == 200, r.text
    ident = admin_client.get("/api/admin/profile/identity").json()
    assert ident["headline"] == "Backend Engineer" and ident["summary"] == "Mine"
    assert ident["full_name"] == "Jane Doe"


def test_inline_edit_and_unknown_temp_id(admin_client, make_job):
    job = make_job(Extracted(sections={"skills": [Item(data={"name": "Pythn"})]}))
    r = apply(admin_client, job, [{"temp_id": "zz", "action": "add"}])
    assert r.status_code == 422
    r = apply(admin_client, job, [{"temp_id": "s1", "action": "add", "data": {"name": "Python"}}])
    assert r.status_code == 200
    assert [s["name"] for s in items(admin_client, "skills")] == ["Python"]


def test_notes_appended_and_emails(admin_client, make_job):
    admin_client.put("/api/admin/profile/notes", json={"content": "Existing note"},
                     headers=csrf(admin_client))  # fmt: skip
    job = make_job(
        Extracted(
            sections={
                "notes": [Item(data={"content": "Honors & awards:\n- Hackathon"})],
                "links": [
                    Item(data={"kind": "email", "value": "jane@home.dev"}),
                    Item(data={"kind": "email", "value": "jane@work.dev"}, default_skip=True),
                ],
            }
        )
    )
    r = apply(admin_client, job, defaults(job))
    assert r.status_code == 200, r.text
    notes = admin_client.get("/api/admin/profile/notes").json()["content"]
    assert notes == "Existing note\n\nHonors & awards:\n- Hackathon"
    assert [link["value"] for link in items(admin_client, "links")] == ["jane@home.dev"]


def test_update_of_deleted_item_fails(admin_client, make_job):
    eid = add(admin_client, "skills", name="Go", notes="old")
    job = make_job(Extracted(sections={"skills": [Item(data={"name": "Go", "notes": "new"})]}))
    admin_client.delete(f"/api/admin/profile/skills/{eid}", headers=csrf(admin_client))
    r = apply(admin_client, job, [{"temp_id": "s1", "action": "update"}])
    assert r.status_code == 422


def test_expired_job_cannot_apply(admin_client, app, make_job):
    from datetime import timedelta

    from mebot.models import ImportJob, utcnow

    job = make_job(Extracted(sections={"skills": [Item(data={"name": "Go"})]}))
    with app.state.session_factory() as db:
        row = db.get(ImportJob, job["id"])
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    r = apply(admin_client, job, defaults(job))
    assert r.status_code == 409 and "expired" in r.json()["error"]["message"]
    assert admin_client.get(f"/api/admin/import/jobs/{job['id']}").json()["status"] == "expired"


def test_reimport_same_resume_proposes_only_changes(admin_client, make_job):
    ex = Extracted(sections={"skills": [Item(data={"name": "Go"}), Item(data={"name": "Rust"})]})
    job = make_job(ex)
    apply(admin_client, job, defaults(job))
    again = make_job(Extracted(sections={"skills": [Item(data={"name": "Go"}),
                                                    Item(data={"name": "Zig"})]}))  # fmt: skip
    statuses = [e["match"]["status"] for e in again["draft"]["sections"]["skills"]]
    assert statuses == ["same", "new"]
