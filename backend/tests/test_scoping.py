from mebot.db import make_session_factory, run_migrations
from mebot.repos import bots, sessions


def test_bot_cannot_read_other_bots_sessions(tmp_path):
    url = f"sqlite:///{(tmp_path / 's.db').as_posix()}"
    run_migrations(url)
    session_factory = make_session_factory(url)
    with session_factory() as db:
        a = bots.create(db, slug="a", name="A")
        b = bots.create(db, slug="b", name="B")
        sid = sessions.create(db, a.id, recruiter_name="x")
        sessions.add_message(db, a.id, sid, "user", "secret")
        db.commit()
        assert sessions.get(db, a.id, sid) is not None
        assert sessions.get(db, b.id, sid) is None
        assert sessions.messages(db, b.id, sid) == []
        assert sessions.list_with_turns(db, b.id) == []
        assert len(sessions.list_with_turns(db, a.id)) == 1


def test_session_from_other_bot_404(admin_client, app):
    with app.state.session_factory() as db:
        other = bots.create(db, slug="other", name="Other")
        sid = sessions.create(db, other.id, recruiter_name=None)
        db.commit()
    assert admin_client.get(f"/api/admin/sessions/{sid}/messages").status_code == 404
    r = admin_client.post("/api/chat", json={"session_id": sid, "message": "hi"})
    assert r.status_code == 404
