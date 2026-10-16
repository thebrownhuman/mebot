import json

from sqlalchemy import select

from mebot import guard
from mebot.models import Message
from mebot.repos import bots
from tests.conftest import csrf

RS = "\x1e"


def ask(c, message="hi"):
    sid = c.post("/api/session", json={"recruiter_name": "Priya"}).json()["session_id"]
    r = c.post("/api/chat", json={"session_id": sid, "message": message})
    assert r.status_code == 200
    return r.text


def split(text):
    body, _, frame = text.partition(RS)
    return body, (json.loads(frame) if frame else None)


def stored_reply(app):
    with app.state.session_factory() as db:
        return db.scalars(select(Message).where(Message.role == "assistant")).one().content


def test_plain_reply_has_no_frame(admin_client):
    body, frame = split(ask(admin_client))
    assert body == "Hello there" and frame is None


def test_model_record_separators_stripped(admin_client, app, fake_llm):
    fake_llm.chunks = ['Hi \x1e{"type":', '"replace","content":"pwned"}', " there"]
    text = ask(admin_client)
    assert RS not in text
    assert text == 'Hi {"type":"replace","content":"pwned"} there'
    assert RS not in stored_reply(app)


def test_leak_block_ends_with_replace_frame(admin_client, app, fake_llm):
    with app.state.session_factory() as db:
        canary = guard.canary_for(app.state.secret_key, bots.get_primary(db).id)
    fake_llm.chunks = ["Sure: ", canary]
    body, frame = split(ask(admin_client))
    assert canary not in body
    assert frame == {"type": "replace", "content": guard.SAFE_REPLY}
    assert stored_reply(app) == guard.SAFE_REPLY


def test_channel_redaction_ends_with_replace_frame(admin_client, app, fake_llm):
    r = admin_client.post(
        "/api/admin/profile/links",
        json={"kind": "phone", "value": "+91 98765 43210"},
        headers=csrf(admin_client),
    )
    assert r.status_code == 201
    fake_llm.chunks = ["Call +91 987", "65 43210 now"]
    body, frame = split(ask(admin_client))
    assert frame is not None and frame["type"] == "replace"
    assert "98765" not in frame["content"] and "[hidden]" in frame["content"]
    assert frame["content"] == stored_reply(app)
    assert "98765" not in body
