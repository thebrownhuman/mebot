from tests.conftest import csrf


def test_unanswered_endpoint(admin_client, fake_llm):
    fake_llm.chunks = ["No idea. [[UNANSWERED]]"]
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    for q in ("Q one?", "Q two?"):
        admin_client.post("/api/chat", json={"session_id": sid, "message": q})
    items = admin_client.get("/api/admin/unanswered", params={"limit": 1}).json()["items"]
    assert len(items) == 1
    assert items[0]["question"] == "Q two?" and items[0]["session_id"] == sid
    assert items[0]["created_at"].endswith("Z")
    admin_client.cookies.pop("mebot_session")
    assert admin_client.get("/api/admin/unanswered").status_code == 401


def test_unanswered_scoped_to_bot(admin_client, app):
    from mebot.repos import bots, logs

    with app.state.session_factory() as db:
        other = bots.create(db, slug="other", name="Other")
        logs.add(db, other.id, "s-x", "UNANSWERED", detail="secret question")
        db.commit()
    assert admin_client.get("/api/admin/unanswered").json() == {"items": []}


def test_facts_endpoint(admin_client):
    c = admin_client
    c.post(
        "/api/admin/profile/experiences",
        json={
            "company": "Acme",
            "title": "Engineer",
            "start_month": "2020-01",
            "end_month": "2020-12",
            "employment_type": "internship",
        },
        headers=csrf(c),
    )
    f = c.get("/api/admin/profile/facts").json()
    assert f["as_of"] and f["total_experience"]["months"] == 0 and f["internship_months"] == 12
    c.put(
        "/api/admin/profile/identity",
        json={"full_name": "J", "count_internships": True},
        headers=csrf(c),
    )
    assert c.get("/api/admin/profile/facts").json()["total_experience"]["months"] == 12
    c.cookies.pop("mebot_session")
    assert c.get("/api/admin/profile/facts").status_code == 401
