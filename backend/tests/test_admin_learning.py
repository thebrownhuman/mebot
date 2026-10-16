import json

import pytest
from sqlalchemy import select

from mebot.models import AvoidTopic, Bot, LearnedFact, OpenQuestion
from mebot.profile.schemas import IdentityIn
from mebot.repos import bots, open_questions
from mebot.repos import profile_items as profile
from tests.conftest import csrf, do_setup

FACT = "Shivansh lives in Bangalore and is open to remote work."


def cleaned(fake_llm, **over):
    out = {
        "fact_text": FACT,
        "section": "learned",
        "field": None,
        "value": None,
        "personal_only": False,
    }
    out.update(over)
    fake_llm.chunks = [json.dumps(out)]


def seed(app, text="Where do you live?", times=1):
    with app.state.session_factory() as db:
        bot_id = bots.get_primary(db).id
        for _ in range(times):
            q, _ = open_questions.record(db, bot_id, text, "s1")
        db.commit()
        return q.id


def post(c, url, body=None):
    return (
        c.post(url, json=body, headers=csrf(c))
        if body is not None
        else c.post(url, headers=csrf(c))
    )


Q = "/api/admin/open-questions"
F = "/api/admin/learned-facts"


def test_auth_required_everywhere(client):
    do_setup(client)
    client.cookies.clear()
    for method, url in (
        ("get", Q),
        ("post", f"{Q}/x/answer"),
        ("post", f"{Q}/x/dismiss"),
        ("post", f"{Q}/x/never"),
        ("get", F),
        ("post", F),
        ("post", f"{F}/x/approve"),
        ("post", f"{F}/x/reject"),
        ("put", f"{F}/x"),
        ("delete", f"{F}/x"),
    ):
        r = getattr(client, method)(url)
        assert r.status_code in (401, 403), (method, url, r.status_code)


def test_csrf_required_for_writes(admin_client, app):
    qid = seed(app)
    assert (
        admin_client.post(f"{Q}/{qid}/dismiss", headers={"X-CSRF-Token": "bad"}).status_code == 403
    )
    assert admin_client.post(f"{Q}/{qid}/dismiss").status_code == 403


def test_list_sorted_and_filtered(admin_client, app):
    seed(app, "alpha topic")
    seed(app, "beta topic", times=3)
    dismissed = seed(app, "gamma topic")
    post(admin_client, f"{Q}/{dismissed}/dismiss")
    r = admin_client.get(Q).json()
    assert [i["question"] for i in r["items"]] == ["beta topic", "alpha topic"]
    assert r["open_count"] == 2
    item = r["items"][0]
    assert item["ask_count"] == 3 and item["status"] == "open"
    assert item["last_asked_at"].endswith("Z") and "normalized" not in item
    assert [
        i["question"] for i in admin_client.get(Q, params={"status": "dismissed"}).json()["items"]
    ] == ["gamma topic"]
    assert len(admin_client.get(Q, params={"status": "all"}).json()["items"]) == 3
    assert admin_client.get(Q, params={"status": "bogus"}).status_code == 422


def test_answer_returns_pending_fact_201(admin_client, app, fake_llm):
    qid = seed(app)
    cleaned(fake_llm, section="identity", field="location", value="Bangalore")
    r = post(admin_client, f"{Q}/{qid}/answer", {"answer": "Bangalore, open to remote"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending" and body["fact_text"] == FACT
    assert body["suggested_section"] == "identity" and body["suggested_field"] == "location"
    assert body["suggested_value"] == "Bangalore"  # contained in the answer
    assert body["current_value"] is None and body["needs_review"] is False
    assert body["open_question_id"] == qid and body["source"] == "admin"
    assert admin_client.get(Q).json()["items"][0]["status"] == "open"  # not answered until approved


def test_answer_validation_and_personal_rejection(admin_client, app, fake_llm):
    qid = seed(app)
    assert post(admin_client, f"{Q}/{qid}/answer", {"answer": "   "}).status_code == 422
    assert post(admin_client, f"{Q}/{qid}/answer", {}).status_code == 422
    cleaned(fake_llm, fact_text="", personal_only=True)
    r = post(admin_client, f"{Q}/{qid}/answer", {"answer": "He is dating someone"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "PERSONAL_ANSWER"
    assert admin_client.get(F).json()["items"] == []
    assert post(admin_client, f"{Q}/nope/answer", {"answer": "x"}).status_code == 404


def test_full_loop_approve_makes_bot_know_it(admin_client, app, fake_llm):
    qid = seed(app)
    cleaned(fake_llm)
    fid = post(admin_client, f"{Q}/{qid}/answer", {"answer": "Bangalore, open to remote"}).json()[
        "id"
    ]
    r = post(admin_client, f"{F}/{fid}/approve", {})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert admin_client.get(Q).json() == {"items": [], "open_count": 0}
    assert (
        admin_client.get(Q, params={"status": "answered"}).json()["items"][0]["answered_fact_id"]
        == fid
    )
    preview = admin_client.get("/api/admin/profile/preview").json()
    assert f"=== LEARNED FACTS (confirmed by Shivansh) ===\n- {FACT}" in preview["text"]
    # approving again (e.g. from Telegram at the same time) is a no-op
    assert post(admin_client, f"{F}/{fid}/approve").json()["status"] == "approved"
    # and the chat prompt contains it
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    admin_client.post(
        "/api/chat",
        json={"session_id": sid, "message": "Where does he live?"},
        headers=csrf(admin_client),
    )
    assert FACT in fake_llm.streams[-1]["messages"][0]["content"]


def test_approve_without_body_and_with_edits(admin_client, app, fake_llm):
    qid = seed(app)
    cleaned(fake_llm)
    fid = post(admin_client, f"{Q}/{qid}/answer", {"answer": "Bangalore"}).json()["id"]
    r = post(admin_client, f"{F}/{fid}/approve", {"fact_text": "Shivansh lives in Bangalore."})
    assert r.json()["fact_text"] == "Shivansh lives in Bangalore."
    assert (
        post(admin_client, f"{F}/{fid}/approve", {"mode": "weird"}).status_code == 200
    )  # idempotent


def test_identity_conflict_409_then_replace_or_keep_both(admin_client, app, fake_llm):
    with app.state.session_factory() as db:
        profile.put_identity(
            db, bots.get_primary(db).id, IdentityIn(full_name="Shivansh", location="Pune")
        )
        db.commit()
    qid = seed(app)
    cleaned(fake_llm, section="identity", field="location", value="Bangalore")
    fact = post(admin_client, f"{Q}/{qid}/answer", {"answer": "Bangalore"}).json()
    assert fact["current_value"] == "Pune"
    r = post(admin_client, f"{F}/{fact['id']}/approve", {})
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "IDENTITY_FIELD_SET"
    assert err["details"] == [{"field": "location", "current": "Pune", "new": "Bangalore"}]
    assert admin_client.get("/api/admin/profile/identity").json()["location"] == "Pune"
    ok = post(admin_client, f"{F}/{fact['id']}/approve", {"mode": "replace"})
    assert ok.status_code == 200
    assert admin_client.get("/api/admin/profile/identity").json()["location"] == "Bangalore"


def test_keep_both_stays_a_learned_fact(admin_client, app, fake_llm):
    with app.state.session_factory() as db:
        profile.put_identity(
            db, bots.get_primary(db).id, IdentityIn(full_name="Shivansh", location="Pune")
        )
        db.commit()
    cleaned(fake_llm, section="identity", field="location", value="Bangalore")
    fid = post(admin_client, F, {"text": "Bangalore"}).json()["id"]
    r = post(admin_client, f"{F}/{fid}/approve", {"mode": "keep_both"}).json()
    assert r["suggested_section"] == "learned"
    assert admin_client.get("/api/admin/profile/identity").json()["location"] == "Pune"
    assert "- " + FACT in admin_client.get("/api/admin/profile/preview").json()["text"]


def test_reject_reopens_question_and_is_idempotent(admin_client, app, fake_llm):
    qid = seed(app)
    cleaned(fake_llm)
    fid = post(admin_client, f"{Q}/{qid}/answer", {"answer": "Bangalore"}).json()["id"]
    post(admin_client, f"{F}/{fid}/approve")
    assert post(admin_client, f"{F}/{fid}/reject").status_code == 409  # approved: delete instead
    fid2 = post(admin_client, f"{Q}/{qid}/answer", {"answer": "Pune"}).json()["id"]
    r = post(admin_client, f"{F}/{fid2}/reject")
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert post(admin_client, f"{F}/{fid2}/reject").json()["status"] == "rejected"
    assert admin_client.get(Q).json()["items"][0]["status"] == "open"  # back in the inbox
    assert post(admin_client, f"{F}/{fid2}/approve").status_code == 409


def test_dismiss_and_never(admin_client, app, fake_llm):
    qa, qb = seed(app, "Shoe size"), seed(app, "Favourite colour")
    r = post(admin_client, f"{Q}/{qa}/dismiss")
    assert r.json()["status"] == "dismissed"
    r = post(admin_client, f"{Q}/{qb}/never")
    assert r.json()["status"] == "never"
    post(admin_client, f"{Q}/{qb}/never")  # idempotent: no second avoid-topic
    with app.state.session_factory() as db:
        topics = list(db.scalars(select(AvoidTopic).where(AvoidTopic.deleted_at.is_(None))))
    assert [(t.topic, "work and experience" in t.reply) for t in topics] == [
        ("Favourite colour", True)
    ]
    assert admin_client.get(Q).json()["items"] == []
    assert post(admin_client, f"{Q}/nope/dismiss").status_code == 404


def test_add_fact_directly_goes_through_cleaning(admin_client, fake_llm):
    cleaned(fake_llm, fact_text="Shivansh speaks Hindi and English.")
    r = post(admin_client, F, {"text": "Hindi, English"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending" and body["question"] == "Added by the owner"
    assert body["open_question_id"] is None
    assert post(admin_client, F, {"text": "  "}).status_code == 422
    fake_llm.chunks = ["definitely not json"]  # provider misbehaves -> flagged fallback
    r = post(admin_client, F, {"text": "Worked on payments", "question": "Domains?"})
    assert (
        r.json()["needs_review"] is True and r.json()["fact_text"] == "Shivansh: Worked on payments"
    )


def test_list_put_delete_facts(admin_client, fake_llm):
    cleaned(fake_llm)
    a = post(admin_client, F, {"text": "Bangalore"}).json()["id"]
    cleaned(fake_llm, fact_text="Shivansh speaks Hindi.")
    b = post(admin_client, F, {"text": "Hindi"}).json()["id"]
    post(admin_client, f"{F}/{b}/approve")
    post(admin_client, f"{F}/{a}/reject")
    assert [
        f["id"] for f in admin_client.get(F, params={"status": "approved"}).json()["items"]
    ] == [b]
    assert [
        f["id"] for f in admin_client.get(F, params={"status": "rejected"}).json()["items"]
    ] == [a]
    listing = admin_client.get(F).json()
    assert listing["active_count"] == 1 and listing["max_active"] == 200
    assert admin_client.get(F, params={"status": "bogus"}).status_code == 422
    r = admin_client.put(
        f"{F}/{b}",
        json={"fact_text": "Shivansh speaks Hindi and Marathi."},
        headers=csrf(admin_client),
    )
    assert r.status_code == 200 and r.json()["fact_text"].endswith("Marathi.")
    assert (
        admin_client.put(f"{F}/{b}", json={"fact_text": ""}, headers=csrf(admin_client)).status_code
        == 422
    )
    assert (
        admin_client.put(
            f"{F}/{a}", json={"fact_text": "x"}, headers=csrf(admin_client)
        ).status_code
        == 409
    )
    assert admin_client.delete(f"{F}/{b}", headers=csrf(admin_client)).status_code == 204
    assert admin_client.delete(f"{F}/{b}", headers=csrf(admin_client)).status_code == 404
    assert "Marathi" not in admin_client.get("/api/admin/profile/preview").json()["text"]
    assert all(f["id"] != b for f in admin_client.get(F).json()["items"])


def test_other_bots_data_is_invisible(admin_client, app, fake_llm):
    cleaned(fake_llm)
    fid = post(admin_client, F, {"text": "Bangalore"}).json()["id"]
    qid = seed(app)
    with app.state.session_factory() as db:
        db.add(Bot(id="other", slug="other", name="Other"))
        db.get(OpenQuestion, qid).bot_id = "other"
        db.get(LearnedFact, fid).bot_id = "other"
        db.commit()
    assert admin_client.get(Q).json()["items"] == []
    assert admin_client.get(F).json()["items"] == []
    assert post(admin_client, f"{Q}/{qid}/dismiss").status_code == 404
    assert post(admin_client, f"{F}/{fid}/approve").status_code == 404
    assert admin_client.delete(f"{F}/{fid}", headers=csrf(admin_client)).status_code == 404


@pytest.mark.parametrize("n", [1])
def test_error_shape(admin_client, n):
    r = post(admin_client, f"{F}/nope/approve")
    assert r.status_code == 404 and set(r.json()["error"]) >= {"code", "message", "status"}
