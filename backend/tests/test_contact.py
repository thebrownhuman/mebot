import json

import pytest
from sqlalchemy import select

from mebot.models import AccessLog, Contact, Notification
from tests.tg_helpers import link

BODY = {
    "name": "Priya",
    "email": "priya@acme.com",
    "company": "Acme",
    "role": "Recruiter",
    "note": "Let's talk <soon>",
}


def contacts(app):
    with app.state.session_factory() as db:
        return list(db.scalars(select(Contact)))


def test_contact_created_and_notified(admin_client, app):
    link(app)
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    r = admin_client.post("/api/contact", json={**BODY, "session_id": sid})
    assert r.status_code == 201 and "id" in r.json()
    [c] = contacts(app)
    assert (c.name, c.email, c.company, c.session_id) == ("Priya", "priya@acme.com", "Acme", sid)
    with app.state.session_factory() as db:
        n = db.scalar(select(Notification).where(Notification.kind == "contact"))
        assert db.scalar(select(AccessLog).where(AccessLog.event == "CONTACT_LEFT"))
    assert "&lt;soon&gt;" in json.loads(n.payload)["text"]
    assert "testclient" not in n.payload


def test_contact_minimal_and_unknown_session(admin_client, app):
    r = admin_client.post(
        "/api/contact", json={"name": "Bo", "email": "bo@x.io", "session_id": "nope"}
    )
    assert r.status_code == 201
    [c] = contacts(app)
    assert c.session_id is None and c.company is None


@pytest.mark.parametrize(
    ("over", "field"),
    [
        ({"name": ""}, "name"),
        ({"name": "   "}, "name"),
        ({"email": "not-an-email"}, "email"),
        ({"note": "x" * 1001}, "note"),
        ({"company": "x" * 201}, "company"),
    ],
)
def test_contact_validation(admin_client, over, field):
    r = admin_client.post("/api/contact", json={**BODY, **over})
    assert r.status_code == 422
    assert r.json()["error"]["details"][0]["field"] == field


def test_honeypot_accepts_silently(admin_client, app):
    link(app)
    r = admin_client.post("/api/contact", json={**BODY, "website": "http://spam.example"})
    assert r.status_code == 201
    assert contacts(app) == []
    with app.state.session_factory() as db:
        assert db.scalars(select(Notification)).all() == []


def test_contact_rate_limit_3_per_hour(admin_client):
    codes = [admin_client.post("/api/contact", json=BODY).status_code for _ in range(4)]
    assert codes == [201, 201, 201, 429]
    r = admin_client.post("/api/contact", json=BODY)
    assert int(r.headers["retry-after"]) > 0
    assert r.json()["error"]["code"] == "RATE_LIMITED"
