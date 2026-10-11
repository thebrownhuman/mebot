import pytest

from mebot.llm import ollama
from mebot.prompt import DEFAULT_PROFILE


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


def test_health_ok(client, fake_ollama):
    assert client.get("/api/health").json() == {"ollama": True, "model": "me-bot"}


def test_default_profile_then_save(client):
    assert client.get("/api/profile").json() == {"content": DEFAULT_PROFILE}
    assert client.put("/api/profile", json={"content": "NAME: X"}).json() == {"ok": True}
    assert client.get("/api/profile").json() == {"content": "NAME: X"}
    log = client.get("/api/log").json()
    assert log[0]["event"] == "profile_updated"
    assert set(log[0]) == {"event", "detail", "ip", "ts"}
    assert isinstance(log[0]["ts"], float)


def test_session_create_and_list(client):
    sid = client.post("/api/session", json={"recruiter_name": "Bob"}).json()["session_id"]
    assert isinstance(sid, str) and len(sid) == 32
    sessions = client.get("/api/sessions").json()
    assert len(sessions) == 1
    s = sessions[0]
    assert set(s) == {"id", "recruiter_name", "started_at", "turns"}
    assert s["id"] == sid and s["recruiter_name"] == "Bob" and s["turns"] == 0
    assert isinstance(s["started_at"], float)
    assert client.get(f"/api/session/{sid}/messages").json() == []
    assert client.get("/api/log").json()[0]["event"] == "session_start"


def test_chat_streams_and_persists(client, fake_ollama):
    client.put("/api/profile", json={"content": "NAME: Zed"})
    sid = client.post("/api/session", json={}).json()["session_id"]
    r = client.post("/api/chat", json={"session_id": sid, "message": "who are you?"})
    assert r.status_code == 200
    assert r.text == "Hello there"
    payload = fake_ollama["payload"]
    assert payload["model"] == "me-bot" and payload["think"] is False
    assert "NAME: Zed" in payload["messages"][0]["content"]
    assert payload["messages"][-1] == {"role": "user", "content": "who are you?"}
    msgs = client.get(f"/api/session/{sid}/messages").json()
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "who are you?"),
        ("assistant", "Hello there"),
    ]
    assert client.get("/api/sessions").json()[0]["turns"] == 2
    client.post("/api/chat", json={"session_id": sid, "message": "more"})
    assert len(fake_ollama["payload"]["messages"]) == 4  # system + 2 history + new


def test_chat_unknown_session(client, fake_ollama):
    r = client.post("/api/chat", json={"session_id": "nope", "message": "hi"})
    assert r.status_code == 404


@pytest.mark.parametrize("msg", ["", "   ", "\n\t"])
def test_chat_empty_message_422(client, fake_ollama, msg):
    sid = client.post("/api/session", json={}).json()["session_id"]
    assert client.post("/api/chat", json={"session_id": sid, "message": msg}).status_code == 422


def test_chat_ollama_unreachable_503(client):
    sid = client.post("/api/session", json={}).json()["session_id"]
    r = client.post("/api/chat", json={"session_id": sid, "message": "hi"})
    assert r.status_code == 503


def test_chat_stream_error_is_streamed(client, monkeypatch):
    async def list_models(host):
        return ["me-bot"]

    async def stream_chat(host, payload):
        yield "partial"
        raise RuntimeError("boom")

    monkeypatch.setattr(ollama, "list_models", list_models)
    monkeypatch.setattr(ollama, "stream_chat", stream_chat)
    sid = client.post("/api/session", json={}).json()["session_id"]
    r = client.post("/api/chat", json={"session_id": sid, "message": "hi"})
    assert r.status_code == 200
    assert r.text.startswith("partial") and "[error contacting model: boom]" in r.text
    msgs = client.get(f"/api/session/{sid}/messages").json()
    assert (msgs[-1]["role"], msgs[-1]["content"]) == ("assistant", "partial")


def test_get_current_bot_creates_default(client, app):
    from mebot.repos import bots

    with app.state.session_factory() as db:
        assert bots.get_by_slug(db, "default") is None
    client.get("/api/profile")
    with app.state.session_factory() as db:
        assert bots.get_by_slug(db, "default") is not None
