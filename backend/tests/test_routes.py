import pytest

from mebot.llm import ollama
from mebot.prompt import DEFAULT_PROFILE
from tests.conftest import csrf


@pytest.fixture
def fake_ollama(monkeypatch):
    calls = {}

    async def list_models(host):
        return ["me-bot", "other"]

    async def stream_chat(host, payload):
        calls["payload"] = payload
        for chunk in ["Hel", "lo ", "there"]:
            yield chunk

    monkeypatch.setattr(ollama, "list_models", list_models)
    monkeypatch.setattr(ollama, "stream_chat", stream_chat)
    return calls


def test_health_ollama_down(client):
    body = client.get("/api/health").json()
    assert body["ollama"] is False and body["model"] is None and "message" in body


def test_health_ok(admin_client, fake_ollama):
    assert admin_client.get("/api/health").json() == {"ollama": True, "model": "me-bot"}


def test_default_profile_then_save(admin_client):
    assert admin_client.get("/api/admin/profile").json() == {"content": DEFAULT_PROFILE}
    assert admin_client.put(
        "/api/admin/profile", json={"content": "NAME: X"}, headers=csrf(admin_client)
    ).json() == {"ok": True}
    assert admin_client.get("/api/admin/profile").json() == {"content": "NAME: X"}
    log = admin_client.get("/api/admin/log").json()
    assert log[0]["event"] == "profile_updated"
    assert set(log[0]) == {"event", "detail", "ip", "ts"}
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


def test_chat_streams_and_persists(admin_client, fake_ollama):
    admin_client.put(
        "/api/admin/profile", json={"content": "NAME: Zed"}, headers=csrf(admin_client)
    )
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    r = admin_client.post("/api/chat", json={"session_id": sid, "message": "who are you?"})
    assert r.status_code == 200
    assert r.text == "Hello there"
    payload = fake_ollama["payload"]
    assert payload["model"] == "me-bot" and payload["think"] is False
    assert "NAME: Zed" in payload["messages"][0]["content"]
    assert payload["messages"][-1] == {"role": "user", "content": "who are you?"}
    msgs = admin_client.get(f"/api/admin/sessions/{sid}/messages").json()
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "who are you?"),
        ("assistant", "Hello there"),
    ]
    assert admin_client.get("/api/admin/sessions").json()[0]["turns"] == 2
    admin_client.post("/api/chat", json={"session_id": sid, "message": "more"})
    assert len(fake_ollama["payload"]["messages"]) == 4  # system + 2 history + new


def test_chat_unknown_session(admin_client, fake_ollama):
    r = admin_client.post("/api/chat", json={"session_id": "nope", "message": "hi"})
    assert r.status_code == 404


@pytest.mark.parametrize("msg", ["", "   ", "\n\t"])
def test_chat_empty_message_422(admin_client, fake_ollama, msg):
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    assert (
        admin_client.post("/api/chat", json={"session_id": sid, "message": msg}).status_code == 422
    )


def test_chat_ollama_unreachable_503(admin_client):
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    r = admin_client.post("/api/chat", json={"session_id": sid, "message": "hi"})
    assert r.status_code == 503


def test_chat_stream_error_is_streamed(admin_client, monkeypatch):
    async def list_models(host):
        return ["me-bot"]

    async def stream_chat(host, payload):
        yield "partial"
        raise RuntimeError("boom")

    monkeypatch.setattr(ollama, "list_models", list_models)
    monkeypatch.setattr(ollama, "stream_chat", stream_chat)
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    r = admin_client.post("/api/chat", json={"session_id": sid, "message": "hi"})
    assert r.status_code == 200
    assert r.text.startswith("partial") and "[error contacting model: boom]" in r.text
    msgs = admin_client.get(f"/api/admin/sessions/{sid}/messages").json()
    assert (msgs[-1]["role"], msgs[-1]["content"]) == ("assistant", "partial")


def test_get_current_bot_creates_default(client, app):
    from mebot.repos import bots

    with app.state.session_factory() as db:
        assert bots.get_by_slug(db, "default") is None
    client.post("/api/session", json={})
    with app.state.session_factory() as db:
        assert bots.get_by_slug(db, "default") is not None
