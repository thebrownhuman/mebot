from sqlalchemy import select

from mebot.models import AccessLog, Message
from tests.conftest import csrf


def add(c, **body):
    r = c.post("/api/admin/profile/links", json=body, headers=csrf(c))
    assert r.status_code == 201, r.text
    return r.json()


def ask(c, message="what's his number?"):
    sid = c.post("/api/session", json={"recruiter_name": "Priya"}).json()["session_id"]
    r = c.post("/api/chat", json={"session_id": sid, "message": message})
    assert r.status_code == 200
    return r.text.partition("\x1e")[0]  # drop the trailing replace frame, if any


def logs(app):
    with app.state.session_factory() as db:
        return list(db.scalars(select(AccessLog).where(AccessLog.event == "CHANNEL_REDACTED")))


def test_reply_never_contains_unshared_phone(admin_client, app, fake_llm):
    add(admin_client, kind="phone", value="+91 98765 43210")
    add(admin_client, kind="email", value="jane@example.com")
    fake_llm.chunks = ["His number is +91 987", "65 43210. Mail jane@exa", "mple.com."]
    text = ask(admin_client)
    assert "98765" not in text and "[hidden]" in text
    assert "jane@example.com" in text
    with app.state.session_factory() as db:
        stored = db.scalars(select(Message).where(Message.role == "assistant")).one().content
    assert stored == text.strip() and "98765" not in stored
    [ev] = logs(app)
    assert "98765" not in (ev.detail or "") and ev.detail == "1"


def test_unshared_handle_redacted_shared_kept(admin_client, app, fake_llm):
    add(admin_client, kind="instagram", value="@private_jane", share=False)
    add(admin_client, kind="whatsapp", value="@jane_wa")
    fake_llm.chunks = ["IG @private_jane or WhatsApp @jane_wa"]
    text = ask(admin_client, "how can I contact him?")
    assert "private_jane" not in text and "@jane_wa" in text


def test_shared_phone_allowed(admin_client, app, fake_llm):
    pid = add(admin_client, kind="phone", value="+91 98765 43210")["id"]
    r = admin_client.put(
        f"/api/admin/profile/links/{pid}",
        json={"share": True, "confirm_share_phone": True},
        headers=csrf(admin_client),
    )
    assert r.status_code == 200
    fake_llm.chunks = ["Call +91 98765 43210"]
    assert "+91 98765 43210" in ask(admin_client)
    assert not logs(app)


def test_invented_phone_redacted(admin_client, app, fake_llm):
    fake_llm.chunks = ["Try 555-123-4567 or 0044 20 7946 0958"]
    text = ask(admin_client)
    assert "555" not in text and "7946" not in text


def test_turning_share_off_takes_effect_immediately(admin_client, app, fake_llm):
    cid = add(admin_client, kind="instagram", value="@jane_ig")["id"]
    fake_llm.chunks = ["IG @jane_ig"]
    assert "@jane_ig" in ask(admin_client)
    r = admin_client.put(
        f"/api/admin/profile/links/{cid}", json={"share": False}, headers=csrf(admin_client)
    )
    assert r.status_code == 200
    assert "jane_ig" not in ask(admin_client)
    sent = "\n".join(m["content"] for m in fake_llm.streams[-1]["messages"])
    assert "jane_ig" not in sent
