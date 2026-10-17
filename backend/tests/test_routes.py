import httpx
import pytest
from sqlalchemy import select

from mebot.llm.base import LLMError
from mebot.models import AccessLog, LLMConfig
from mebot.routes.chat import UNAVAILABLE
from tests.conftest import LLM_KEY, csrf


def test_health_before_setup(client):
    body = client.get("/api/health").json()
    assert body["ready"] is False and body["model"] is None and "message" in body


def test_health_ready_after_setup(admin_client, fake_llm):
    assert admin_client.get("/api/health").json() == {"ready": True, "model": "gpt-4o-mini"}
    assert fake_llm.tests == ["gpt-4o-mini"]  # health makes no provider call


def test_health_not_ready_after_failed_test(admin_client, app):
    with app.state.session_factory() as db:
        db.scalar(select(LLMConfig)).last_test_ok = False
        db.commit()
    body = admin_client.get("/api/health").json()
    assert body["ready"] is False and "message" in body


def test_profile_change_is_logged(admin_client):
    r = admin_client.put(
        "/api/admin/profile/notes", json={"content": "NAME: X"}, headers=csrf(admin_client)
    )
    assert r.json() == {"content": "NAME: X"}
    log = admin_client.get("/api/admin/log").json()
    assert log[0]["event"] == "profile_updated" and log[0]["detail"] == "notes"
    assert set(log[0]) == {"event", "detail", "ip_hash", "ts"}
    assert isinstance(log[0]["ts"], float)


def test_session_create_and_list(admin_client):
    sid = admin_client.post("/api/session", json={"recruiter_name": "Bob"}).json()["session_id"]
    assert isinstance(sid, str) and len(sid) == 32
    sessions = admin_client.get("/api/admin/sessions").json()
    assert len(sessions) == 1
    s = sessions[0]
    assert set(s) == {"id", "recruiter_name", "started_at", "turns"}
    assert s["id"] == sid and s["recruiter_name"] == "Bob" and s["turns"] == 0
    assert isinstance(s["started_at"], float)
    assert admin_client.get(f"/api/admin/sessions/{sid}/messages").json() == []
    assert admin_client.get("/api/admin/log").json()[0]["event"] == "session_start"


def test_chat_streams_and_persists(admin_client, fake_llm):
    admin_client.put(
        "/api/admin/profile/notes", json={"content": "NAME: Zed"}, headers=csrf(admin_client)
    )
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    r = admin_client.post("/api/chat", json={"session_id": sid, "message": "who are you?"})
    assert r.status_code == 200
    assert r.text == "Hello there"
    assert fake_llm.built[-1] == {"provider": "openai", "api_key": LLM_KEY, "base_url": None}
    call = fake_llm.streams[-1]
    assert call["model"] == "gpt-4o-mini"
    assert call["temperature"] == 0.4 and call["max_tokens"] == 600
    assert "NAME: Zed" in call["messages"][0]["content"]
    assert call["messages"][-1] == {
        "role": "user",
        "content": "<visitor_message>\nwho are you?\n</visitor_message>",
    }
    msgs = admin_client.get(f"/api/admin/sessions/{sid}/messages").json()
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "who are you?"),
        ("assistant", "Hello there"),
    ]
    assert admin_client.get("/api/admin/sessions").json()[0]["turns"] == 2
    admin_client.post("/api/chat", json={"session_id": sid, "message": "more"})
    assert len(fake_llm.streams[-1]["messages"]) == 4  # system + 2 history + new


def test_chat_unknown_session(admin_client):
    r = admin_client.post("/api/chat", json={"session_id": "nope", "message": "hi"})
    assert r.status_code == 404


@pytest.mark.parametrize("msg", ["", "   ", "\n\t"])
def test_chat_empty_message_422(admin_client, msg):
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    assert (
        admin_client.post("/api/chat", json={"session_id": sid, "message": msg}).status_code == 422
    )


@pytest.mark.parametrize(
    "err",
    [
        LLMError("auth", f"OpenAI rejected the API key (401): bad {LLM_KEY}", 401),
        LLMError("rate_limit", "OpenAI rate limited the request, try again shortly.", 429),
        LLMError("timeout", "Timed out contacting OpenAI."),
    ],
)
def test_chat_provider_error_is_friendly_and_logged(admin_client, app, fake_llm, err):
    fake_llm.stream_fail = err
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    r = admin_client.post("/api/chat", json={"session_id": sid, "message": "hi"})
    assert r.status_code == 200
    assert r.text == UNAVAILABLE
    assert LLM_KEY not in r.text
    with app.state.session_factory() as db:
        rows = list(db.scalars(select(AccessLog).where(AccessLog.event == "LLM_ERROR")))
        cfg = db.scalar(select(LLMConfig))
    assert len(rows) == 1
    assert "provider=openai" in rows[0].detail and f"kind={err.kind}" in rows[0].detail
    assert str(err.status) in rows[0].detail
    assert LLM_KEY not in rows[0].detail and "rejected" not in rows[0].detail
    assert cfg.last_test_ok is False
    assert admin_client.get("/api/admin/llm").json()["last_test_ok"] is False


def test_chat_unexpected_error_is_friendly(admin_client, fake_llm):
    fake_llm.stream_fail = httpx.ReadError("boom")
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    r = admin_client.post("/api/chat", json={"session_id": sid, "message": "hi"})
    assert r.text == UNAVAILABLE


def test_chat_partial_then_error_keeps_partial(admin_client, fake_llm):
    fake_llm.chunks = ["partial"]
    fake_llm.fail_after = LLMError("provider", "OpenAI returned a server error (502)", 502)
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    r = admin_client.post("/api/chat", json={"session_id": sid, "message": "hi"})
    assert r.text.startswith("partial") and UNAVAILABLE in r.text
    msgs = admin_client.get(f"/api/admin/sessions/{sid}/messages").json()
    assert (msgs[-1]["role"], msgs[-1]["content"]) == ("assistant", "partial")


def test_chat_503_when_llm_not_configured(admin_client, app):
    with app.state.session_factory() as db:
        db.query(LLMConfig).delete()
        db.commit()
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    r = admin_client.post("/api/chat", json={"session_id": sid, "message": "hi"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "LLM_NOT_CONFIGURED"


def test_chat_503_when_key_undecryptable(admin_client, app):
    app.state.secret_key = "rotated"
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    r = admin_client.post("/api/chat", json={"session_id": sid, "message": "hi"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "LLM_NOT_CONFIGURED"


def test_get_current_bot_creates_default(client, app):
    from mebot.repos import bots

    with app.state.session_factory() as db:
        assert bots.get_by_slug(db, "default") is None
    client.post("/api/session", json={})
    with app.state.session_factory() as db:
        assert bots.get_by_slug(db, "default") is not None


def test_chat_prompt_uses_structured_profile(admin_client, fake_llm):
    c = admin_client
    c.put(
        "/api/admin/profile/identity",
        json={"full_name": "Jane Doe", "headline": "Backend engineer"},
        headers=csrf(c),
    )
    c.post(
        "/api/admin/profile/projects",
        json={"name": "mebot", "summary": "Portfolio chatbot", "backend": "FastAPI"},
        headers=csrf(c),
    )
    c.post(
        "/api/admin/profile/avoid-topics",
        json={"topic": "Politics", "reply": "I keep politics out of work chats."},
        headers=csrf(c),
    )
    sid = c.post("/api/session", json={}).json()["session_id"]
    c.post("/api/chat", json={"session_id": sid, "message": "what is mebot built with?"})
    system = fake_llm.streams[-1]["messages"][0]["content"]
    assert "=== IDENTITY ===" in system and "Jane Doe" in system
    assert "=== PROJECTS ===" in system and "Backend: FastAPI" in system
    assert "=== AVOID ===" in system and "I keep politics out of work chats." in system
    assert "AVOID" in system.split("PROFILE:")[0]  # the rule that explains AVOID
    assert "[Your name]" not in system  # old template never leaks into the prompt


def test_visitor_and_admin_ips_are_stored_hashed(admin_client):
    import sqlalchemy as sa

    from mebot.limits.counters import ip_hash

    admin_client.post("/api/session", json={"recruiter_name": "Bob"})
    key = admin_client.app.state.secret_key
    with admin_client.app.state.session_factory() as db:
        logged = db.execute(
            sa.text("SELECT ip_hash FROM access_log WHERE event='session_start'")
        ).scalar_one()
        admin = db.execute(sa.text("SELECT ip_hash FROM admin_sessions")).scalars().all()
    assert logged == ip_hash(key, "testclient")
    assert admin and all(h == ip_hash(key, "testclient") for h in admin)
    entry = admin_client.get("/api/admin/log").json()[0]
    assert entry["ip_hash"] == logged[:12]
