import pytest

from mebot.profile.sections import SECTIONS
from mebot.repos import bots
from tests.conftest import csrf

BASE = "/api/admin/profile"

SAMPLES = {
    "links": {"label": "GitHub", "url": "https://github.com/jane"},
    "experiences": {
        "company": "Acme",
        "title": "Backend Engineer",
        "employment_type": "full-time",
        "start_month": "2021-04",
        "end_month": None,
        "description": "APIs",
        "highlights": ["Cut p99 by 40%"],
        "tech": ["Go", "Postgres"],
    },
    "educations": {
        "institution": "MIT",
        "degree": "BSc",
        "field": "CS",
        "start_month": "2015-09",
        "end_month": "2019-06",
    },
    "skills": {"name": "Python", "category": "language", "level": "expert"},
    "projects": {
        "name": "mebot",
        "summary": "Self-hostable portfolio chatbot",
        "frontend": "React + Vite",
        "backend": "FastAPI + SQLAlchemy",
        "infra": "Docker",
        "tech": ["Python", "React"],
        "highlights": ["Owner adds own LLM key"],
        "repo_url": "https://github.com/jane/mebot",
    },
    "interests": {"kind": "hobby", "name": "Bouldering", "description": "V5 on a good day"},
    "faqs": {"question": "Open to relocation?", "answer": "Yes, within the EU."},
    "avoid-topics": {"topic": "Salary at current job", "reply": "I'd rather not share that."},
}


def post(c, section, body):
    return c.post(f"{BASE}/{section}", json=body, headers=csrf(c))


# --- collections ---------------------------------------------------------------------


@pytest.mark.parametrize("section", sorted(SECTIONS))
def test_crud_each_section(admin_client, section):
    c = admin_client
    assert c.get(f"{BASE}/{section}").json() == {"items": []}
    r = post(c, section, SAMPLES[section])
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["id"] and item["sort_order"] == 0 and item["created_at"].endswith("Z")
    for k, v in SAMPLES[section].items():
        assert item[k] == v, k
    second = post(c, section, SAMPLES[section]).json()
    assert second["sort_order"] == 1

    ids = [i["id"] for i in c.get(f"{BASE}/{section}").json()["items"]]
    assert ids == [item["id"], second["id"]]

    first_field = next(iter(SAMPLES[section]))
    changed = {**SAMPLES[section]}
    if first_field == "kind":
        first_field = "name"
    changed[first_field] = "Changed"
    r = c.put(f"{BASE}/{section}/{item['id']}", json=changed, headers=csrf(c))
    assert r.status_code == 200 and r.json()[first_field] == "Changed"

    r = c.put(f"{BASE}/{section}/order", json={"ids": [second["id"], item["id"]]}, headers=csrf(c))
    assert r.status_code == 204
    assert [i["id"] for i in c.get(f"{BASE}/{section}").json()["items"]] == [
        second["id"],
        item["id"],
    ]

    assert c.delete(f"{BASE}/{section}/{item['id']}", headers=csrf(c)).status_code == 204
    assert [i["id"] for i in c.get(f"{BASE}/{section}").json()["items"]] == [second["id"]]
    assert c.delete(f"{BASE}/{section}/{item['id']}", headers=csrf(c)).status_code == 404
    r = c.put(f"{BASE}/{section}/{item['id']}", json=SAMPLES[section], headers=csrf(c))
    assert r.status_code == 404


def test_unknown_section_404(admin_client):
    assert admin_client.get(f"{BASE}/hobbies").status_code == 404
    assert post(admin_client, "hobbies", {}).status_code == 404


@pytest.mark.parametrize(
    "section,body,field",
    [
        ("experiences", {**SAMPLES["experiences"], "end_month": "2020-01"}, "end_month"),
        ("experiences", {**SAMPLES["experiences"], "start_month": "2021-13"}, "start_month"),
        ("links", {"label": "x", "url": "javascript:alert(1)"}, "url"),
        ("projects", {**SAMPLES["projects"], "tech": ["x"] * 31}, "tech"),
        ("projects", {**SAMPLES["projects"], "name": "x" * 201}, "name"),
        ("faqs", {"question": "q"}, "answer"),
    ],
)
def test_validation_errors(admin_client, section, body, field):
    r = post(admin_client, section, body)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert any(d["field"] == field for d in err["details"]), err


def test_item_cap(admin_client, monkeypatch):
    from mebot.profile import sections

    monkeypatch.setattr(sections, "MAX_ITEMS", 2)
    for _ in range(2):
        assert post(admin_client, "faqs", SAMPLES["faqs"]).status_code == 201
    r = post(admin_client, "faqs", SAMPLES["faqs"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "LIMIT_REACHED"


def test_reorder_bad_ids_422(admin_client):
    a = post(admin_client, "links", SAMPLES["links"]).json()["id"]
    b = post(admin_client, "links", SAMPLES["links"]).json()["id"]
    for ids in ([a], [a, b, "other"], [a, a]):
        r = admin_client.put(f"{BASE}/links/order", json={"ids": ids}, headers=csrf(admin_client))
        assert r.status_code == 422
    assert [i["id"] for i in admin_client.get(f"{BASE}/links").json()["items"]] == [a, b]


def test_other_bots_items_404(admin_client, app):
    from mebot.profile.schemas import FaqIn
    from mebot.profile.sections import get_section
    from mebot.repos import profile_items

    with app.state.session_factory() as db:
        other = bots.create(db, slug="other", name="Other")
        row = profile_items.create(
            db, get_section("faqs"), other.id, FaqIn(question="q", answer="a")
        )
        db.commit()
        rid = row.id
    c = admin_client
    assert c.put(f"{BASE}/faqs/{rid}", json=SAMPLES["faqs"], headers=csrf(c)).status_code == 404
    assert c.delete(f"{BASE}/faqs/{rid}", headers=csrf(c)).status_code == 404
    assert c.get(f"{BASE}/faqs").json() == {"items": []}
    r = c.put(f"{BASE}/faqs/order", json={"ids": [rid]}, headers=csrf(c))
    assert r.status_code == 422


# --- singletons ------------------------------------------------------------------------


def test_identity_get_put(admin_client):
    c = admin_client
    got = c.get(f"{BASE}/identity").json()
    assert got["full_name"] == "Shivansh"  # pre-filled from the bot name at setup
    body = {
        "full_name": "Jane Doe",
        "headline": "Backend engineer",
        "location": "Berlin",
        "open_to": "remote",
        "summary": "I build APIs.",
        "email_public": "jane@example.com",
    }
    r = c.put(f"{BASE}/identity", json=body, headers=csrf(c))
    assert r.status_code == 200
    got = c.get(f"{BASE}/identity").json()
    for k, v in body.items():
        assert got[k] == v
    assert got["photo_url"] is None
    r = c.put(f"{BASE}/identity", json={"photo_url": "javascript:x"}, headers=csrf(c))
    assert r.status_code == 422


def test_notes_get_put(admin_client):
    c = admin_client
    assert c.get(f"{BASE}/notes").json()["content"] == ""
    assert (
        c.put(f"{BASE}/notes", json={"content": "Likes tea."}, headers=csrf(c)).status_code == 200
    )
    assert c.get(f"{BASE}/notes").json()["content"] == "Likes tea."
    r = c.put(f"{BASE}/notes", json={"content": "x" * 20001}, headers=csrf(c))
    assert r.status_code == 422


def test_old_blob_endpoint_removed(admin_client):
    assert admin_client.get(BASE).status_code in (404, 405)
    r = admin_client.put(BASE, json={"content": "x"}, headers=csrf(admin_client))
    assert r.status_code in (404, 405)


# --- preview -------------------------------------------------------------------------


def test_preview_renders_sections_and_omits_empty(admin_client):
    c = admin_client
    p = c.get(f"{BASE}/preview").json()
    assert "Shivansh" in p["text"]
    for header in ("EXPERIENCE", "PROJECTS", "FAQ", "AVOID", "NOTES"):
        assert header not in p["text"]
    assert p["chars"] == len(p["text"]) and p["approx_tokens"] > 0

    for section, body in SAMPLES.items():
        post(c, section, body)
    c.put(f"{BASE}/notes", json={"content": "Prefers async teams."}, headers=csrf(c))
    text = c.get(f"{BASE}/preview").json()["text"]
    for header in (
        "IDENTITY",
        "EXPERIENCE",
        "EDUCATION",
        "SKILLS",
        "PROJECTS",
        "INTERESTS & HOBBIES",
        "FAQ",
        "AVOID",
        "NOTES",
    ):
        assert header in text, header
    for needle in (
        "Backend Engineer",
        "Acme",
        "2021-04 to present",
        "Cut p99 by 40%",
        "FastAPI + SQLAlchemy",
        "Bouldering",
        "Open to relocation?",
        "Salary at current job",
        "I'd rather not share that.",
        "Prefers async teams.",
        "https://github.com/jane",
    ):
        assert needle in text, needle


# --- protection ------------------------------------------------------------------------

ROUTES = [
    ("GET", f"{BASE}/identity"),
    ("PUT", f"{BASE}/identity"),
    ("GET", f"{BASE}/notes"),
    ("PUT", f"{BASE}/notes"),
    ("GET", f"{BASE}/preview"),
    ("GET", f"{BASE}/projects"),
    ("POST", f"{BASE}/projects"),
    ("PUT", f"{BASE}/projects/order"),
    ("PUT", f"{BASE}/projects/x"),
    ("DELETE", f"{BASE}/projects/x"),
]


@pytest.mark.parametrize("method,path", ROUTES)
def test_auth_required(admin_client, method, path):
    admin_client.cookies.pop("mebot_session")
    r = admin_client.request(method, path, json={}, headers=csrf(admin_client))
    assert r.status_code == 401


@pytest.mark.parametrize("method,path", [r for r in ROUTES if r[0] != "GET"])
def test_csrf_required(admin_client, method, path):
    r = admin_client.request(method, path, json={})
    assert r.status_code == 403


def test_identity_experience_toggles(admin_client):
    c = admin_client
    got = c.get(f"{BASE}/identity").json()
    assert got["count_internships"] is False and got["count_freelance"] is True
    r = c.put(
        f"{BASE}/identity",
        json={"full_name": "Jane", "count_internships": True, "count_freelance": False},
        headers=csrf(c),
    )
    assert r.status_code == 200
    got = c.get(f"{BASE}/identity").json()
    assert got["count_internships"] is True and got["count_freelance"] is False
