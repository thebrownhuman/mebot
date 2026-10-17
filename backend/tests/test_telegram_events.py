import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from mebot import tz
from mebot.models import ChatSession, Contact, Message, Notification, TelegramConfig
from mebot.telegram import events
from tests.conftest import csrf
from tests.test_chat_limits import chat, set_limits
from tests.tg_helpers import link


def notes(app, kind=None):
    with app.state.session_factory() as db:
        q = select(Notification).order_by(Notification.created_at)
        if kind:
            q = q.where(Notification.kind == kind)
        return list(db.scalars(q))


def text_of(n) -> str:
    return json.loads(n.payload)["text"]


def start(c, name="Priya (Acme)"):
    return c.post("/api/session", json={"recruiter_name": name}).json()["session_id"]


def test_nothing_queued_when_not_linked(admin_client, app):
    sid = start(admin_client)
    chat(admin_client, sid)
    assert notes(app) == []


def test_new_session_text_and_toggle(admin_client, app):
    link(app)
    start(admin_client, "<b>Priya</b>")
    [n] = notes(app, "new_session")
    assert text_of(n).startswith("🟢 New chat — <b>&lt;b&gt;Priya&lt;/b&gt;</b>")
    start(admin_client, None)
    assert "Anonymous" in text_of(notes(app, "new_session")[-1])
    link(app, notify_new_session=False)
    start(admin_client)
    assert len(notes(app, "new_session")) == 2


def test_every_question_off_by_default_then_escaped(admin_client, app):
    link(app)
    sid = start(admin_client, "Bo")
    chat(admin_client, sid, "hi")
    assert notes(app, "question") == []
    link(app, notify_every_question=True)
    chat(admin_client, sid, "<script>alert(1)</script>")
    [n] = notes(app, "question")
    assert text_of(n) == "💬 <b>Bo</b>: &lt;script&gt;alert(1)&lt;/script&gt;"


def test_unanswered_with_buttons_and_ref(admin_client, app, fake_llm):
    link(app)
    app.state.settings.public_url = "https://bot.example.com/"
    fake_llm.chunks = ["I don't know that. ", "[[UNANSWERED]]"]
    sid = start(admin_client, "Priya")
    chat(admin_client, sid, "What's your expected CTC?")
    [n] = notes(app, "unanswered")
    data = json.loads(n.payload)
    assert data["text"].startswith("❓ Unanswered from <b>Priya</b>:\nWhat's your expected CTC?")
    [buttons] = data["reply_markup"]["inline_keyboard"]
    assert buttons[0] == {"text": "Reply", "callback_data": f"reply:{n.id}"}
    assert buttons[1]["url"] == f"https://bot.example.com/admin?session={sid}"
    assert n.session_id == sid and n.ref_message_id
    with app.state.session_factory() as db:
        assert db.get(Message, n.ref_message_id).role == "assistant"
    assert "testclient" not in n.payload  # no IP


def test_truncated_to_800():
    out = events.esc("x" * 2000)
    assert len(out) == 800 and out.endswith("…")


def test_contact_text(admin_client, app):
    bot_id = link(app)
    with app.state.session_factory() as db:
        c = Contact(
            bot_id=bot_id,
            name="Priya",
            email="p@acme.com",
            company="Acme",
            role="HR",
            note="Call me <maybe>",
        )
        db.add(c)
        db.flush()
        events.contact(db, bot_id, c)
        db.commit()
    [n] = notes(app, "contact")
    assert text_of(n) == "📇 Contact left — Priya, p@acme.com, Acme, HR\nCall me &lt;maybe&gt;"


def test_pause_resume_alerts(admin_client, app):
    link(app)
    h = csrf(admin_client)
    admin_client.put("/api/admin/limits", json={"paused": True}, headers=h)
    admin_client.put("/api/admin/limits", json={"paused": True}, headers=h)
    admin_client.put("/api/admin/limits", json={"paused": False}, headers=h)
    texts = [text_of(n) for n in notes(app, "limits")]
    assert len(texts) == 2 and "paused" in texts[0] and "running" in texts[1]


def test_cap_warning_once_per_day(admin_client, app):
    link(app)
    set_limits(app, daily_message_cap=5)
    sid = start(admin_client)
    for _ in range(5):
        chat(admin_client, sid)
    [n] = notes(app, "limits")
    assert "80%" in text_of(n) and "(4/5)" in text_of(n)


def test_limits_toggle_off(admin_client, app):
    link(app, notify_limits=False)
    admin_client.put("/api/admin/limits", json={"paused": True}, headers=csrf(admin_client))
    assert notes(app, "limits") == []


def test_leak_alert_hourly(admin_client, app):
    bot_id = link(app)
    t = datetime(2026, 10, 16, 10, tzinfo=UTC)
    with app.state.session_factory() as db:
        for dt in (t, t + timedelta(minutes=30), t + timedelta(minutes=61)):
            events.leak_blocked(db, bot_id, dt)
        db.commit()
    assert len(notes(app, "limits")) == 2


# --- digest -------------------------------------------------------------------------


def _activity(app, bot_id, at: datetime, question="What stack?"):
    with app.state.session_factory() as db:
        s = ChatSession(id=f"s{at.timestamp()}", bot_id=bot_id, recruiter_name="X", started_at=at)
        db.add(s)
        db.add(
            Message(bot_id=bot_id, session_id=s.id, role="user", content=question, created_at=at)
        )
        db.add(
            Message(
                bot_id=bot_id,
                session_id=s.id,
                role="assistant",
                content="?",
                created_at=at + timedelta(seconds=1),
                unanswered=True,
            )
        )
        db.commit()


def _digest(app, now):
    with app.state.session_factory() as db:
        row = db.scalar(select(TelegramConfig))
        sent = events.maybe_digest(db, row, now)
        db.commit()
        return sent


def test_digest_at_hour_in_owner_tz_once(admin_client, app):
    bot_id = link(app, timezone="Asia/Kolkata", digest_hour=21)
    _activity(app, bot_id, datetime(2026, 10, 16, 5, tzinfo=UTC))  # 10:30 IST
    _activity(app, bot_id, datetime(2026, 10, 16, 6, tzinfo=UTC), "what stack?")
    assert not _digest(app, datetime(2026, 10, 16, 15, 29, tzinfo=UTC))  # 20:59 IST
    assert _digest(app, datetime(2026, 10, 16, 15, 30, tzinfo=UTC))  # 21:00 IST
    assert not _digest(app, datetime(2026, 10, 16, 17, 0, tzinfo=UTC))  # same local date
    [n] = notes(app, "daily_digest")
    t = text_of(n)
    assert "2026-10-16" in t and "Chats: 2 · Messages: 2" in t and "Unanswered: 2" in t
    assert "what stack? (2)" in t


def test_digest_skipped_without_activity(admin_client, app):
    link(app, digest_hour=9)
    assert not _digest(app, datetime(2026, 10, 16, 10, tzinfo=UTC))
    assert notes(app, "daily_digest") == []
    with app.state.session_factory() as db:
        assert db.scalar(select(TelegramConfig)).last_digest_date == "2026-10-16"


def test_digest_across_dst_change(admin_client, app):
    # New York leaves DST on 2026-11-01: 21:00 local is 01:00 UTC before, 02:00 UTC after.
    bot_id = link(app, timezone="America/New_York", digest_hour=21)
    _activity(app, bot_id, datetime(2026, 10, 31, 15, tzinfo=UTC))
    _activity(app, bot_id, datetime(2026, 11, 1, 18, tzinfo=UTC))
    assert _digest(app, datetime(2026, 11, 1, 1, 0, tzinfo=UTC))  # Oct 31, 21:00 EDT
    assert not _digest(app, datetime(2026, 11, 1, 5, 0, tzinfo=UTC))  # still Oct 31 local
    assert not _digest(app, datetime(2026, 11, 2, 1, 30, tzinfo=UTC))  # Nov 1, 20:30 EST
    assert _digest(app, datetime(2026, 11, 2, 2, 0, tzinfo=UTC))  # Nov 1, 21:00 EST
    dates = [text_of(n).split("— ")[1][:10] for n in notes(app, "daily_digest")]
    assert dates == ["2026-10-31", "2026-11-01"]


def test_digest_disabled(admin_client, app):
    bot_id = link(app, daily_digest=False, digest_hour=0)
    _activity(app, bot_id, datetime(2026, 10, 16, 5, tzinfo=UTC))
    assert not _digest(app, datetime(2026, 10, 16, 23, tzinfo=UTC))


def test_bad_timezone_falls_back_to_utc():
    assert str(tz.safe_zone("Mars/Olympus")) == "UTC"
