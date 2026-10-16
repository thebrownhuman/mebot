import json
from datetime import timedelta

import httpx
import respx
from sqlalchemy import select

from mebot.models import Notification, utcnow
from mebot.telegram import outbox
from tests.tg_helpers import BASE, ctx, link, mock_telegram, ok, sent_texts


def enqueue(app, bot_id, text, **kw):
    with app.state.session_factory() as db:
        n = outbox.enqueue(db, bot_id, "test", {"text": text}, **kw)
        db.commit()
        return n.id


def rows(app):
    with app.state.session_factory() as db:
        return list(db.scalars(select(Notification).order_by(Notification.created_at)))


class FakeSleep:
    def __init__(self):
        self.calls: list[float] = []

    async def __call__(self, s):
        self.calls.append(s)


def tctx(app, now=None):
    c = ctx(app, now=now)
    c.sleep = FakeSleep()
    return c


def test_enqueue_is_in_callers_transaction(admin_client, app):
    bot_id = link(app)
    with app.state.session_factory() as db:
        outbox.enqueue(db, bot_id, "k", {"text": "x"})
        db.rollback()
    assert rows(app) == []


@respx.mock
async def test_sends_in_order_with_pacing(admin_client, app):
    routes = mock_telegram()
    bot_id = link(app)
    for t in ("one", "two", "three"):
        enqueue(app, bot_id, t)
    c = tctx(app)
    c.clock = lambda: 100.0  # frozen: the test must not depend on how fast the sends are
    assert await outbox.send_due(c) == 3
    assert sent_texts(routes) == ["one", "two", "three"]
    assert [r.status for r in rows(app)] == ["sent"] * 3
    assert all(r.telegram_message_id for r in rows(app))
    # <= 1 message per second per chat: the 2nd and 3rd waited
    assert c.sleep.calls == [outbox.PER_CHAT_GAP, outbox.PER_CHAT_GAP]
    body = json.loads(routes["sendMessage"].calls[0].request.content)
    assert body["parse_mode"] == "HTML"


@respx.mock
async def test_reply_markup_passed(admin_client, app):
    routes = mock_telegram()
    bot_id = link(app)
    kb = {"inline_keyboard": [[{"text": "Reply", "callback_data": "r"}]]}
    with app.state.session_factory() as db:
        outbox.enqueue(db, bot_id, "k", {"text": "x", "reply_markup": kb})
        db.commit()
    await outbox.send_due(tctx(app))
    assert json.loads(routes["sendMessage"].calls[0].request.content)["reply_markup"] == kb


@respx.mock
async def test_429_honours_retry_after_and_keeps_order(admin_client, app):
    mock_telegram()
    bot_id = link(app)
    enqueue(app, bot_id, "first")
    enqueue(app, bot_id, "second")
    respx.post(f"{BASE}/sendMessage").mock(
        return_value=httpx.Response(
            429, json={"ok": False, "error_code": 429, "parameters": {"retry_after": 30}}
        )
    )
    now = utcnow()
    assert await outbox.send_due(tctx(app, now=lambda: now)) == 0
    first, second = rows(app)
    assert first.status == "pending" and first.attempts == 0
    assert first.next_attempt_at >= now + timedelta(seconds=30)
    assert second.status == "pending"  # not sent ahead of the first
    respx.post(f"{BASE}/sendMessage").mock(return_value=ok({"message_id": 9}))
    assert await outbox.send_due(tctx(app, now=lambda: now)) == 0  # still waiting
    later = now + timedelta(seconds=31)
    assert await outbox.send_due(tctx(app, now=lambda: later)) == 2


@respx.mock
async def test_backoff_then_dead_after_6(admin_client, app):
    mock_telegram()
    bot_id = link(app)
    enqueue(app, bot_id, "x")
    respx.post(f"{BASE}/sendMessage").mock(side_effect=httpx.ConnectError("down"))
    t = utcnow()
    delays = []
    for _ in range(6):
        await outbox.send_due(tctx(app, now=lambda t=t: t))
        [r] = rows(app)
        if r.status == "dead":
            break
        delays.append((r.next_attempt_at - t).total_seconds())
        t = r.next_attempt_at
    [r] = rows(app)
    assert r.status == "dead" and r.attempts == 6
    assert delays == sorted(delays) and delays[0] >= 5
    assert "987654" not in (r.last_error or "")


@respx.mock
async def test_permanent_error_goes_dead(admin_client, app):
    mock_telegram()
    bot_id = link(app)
    enqueue(app, bot_id, "x")
    respx.post(f"{BASE}/sendMessage").mock(
        return_value=httpx.Response(
            400, json={"ok": False, "error_code": 400, "description": "chat not found"}
        )
    )
    await outbox.send_due(tctx(app))
    [r] = rows(app)
    assert r.status == "dead" and "chat not found" in r.last_error


@respx.mock
async def test_survives_restart(admin_client, app):
    routes = mock_telegram()
    bot_id = link(app)
    enqueue(app, bot_id, "queued before restart")
    # a brand-new context (as after a process restart) picks it up from the DB
    assert await outbox.send_due(tctx(app)) == 1
    assert sent_texts(routes) == ["queued before restart"]


async def test_unlinked_bot_waits(admin_client, app):
    bot_id = link(app, chat_id=None)
    enqueue(app, bot_id, "x")
    assert await outbox.send_due(tctx(app)) == 0
    assert rows(app)[0].status == "pending"


def test_purge_old(admin_client, app):
    bot_id = link(app)
    with app.state.session_factory() as db:
        old = outbox.enqueue(db, bot_id, "k", {"text": "x"})
        old.status = "sent"
        old.updated_at = utcnow() - timedelta(days=31)
        outbox.enqueue(db, bot_id, "k", {"text": "y"})
        db.commit()
        assert outbox.purge(db) == 1
        db.commit()
    assert len(rows(app)) == 1


def test_enqueue_order_survives_equal_clock(admin_client, app, monkeypatch):
    bot_id = link(app)
    frozen = utcnow()
    monkeypatch.setattr(outbox, "utcnow", lambda: frozen)
    for t in ("a", "b", "c"):
        enqueue(app, bot_id, t)
    got = rows(app)
    assert [json.loads(r.payload)["text"] for r in got] == ["a", "b", "c"]
    assert got[0].created_at < got[1].created_at < got[2].created_at


@respx.mock
async def test_equal_clock_burst_is_all_due_now(admin_client, app, monkeypatch):
    # Regression: the created_at tie-break must not push next_attempt_at into the
    # future, or a burst queued in one clock tick blocks behind itself.
    routes = mock_telegram()
    bot_id = link(app)
    frozen = utcnow()
    monkeypatch.setattr(outbox, "utcnow", lambda: frozen)
    for t in ("a", "b", "c"):
        enqueue(app, bot_id, t)
    naive = frozen.replace(tzinfo=None)
    assert all(r.next_attempt_at.replace(tzinfo=None) <= naive for r in rows(app))
    c = tctx(app, now=lambda: frozen)
    assert await outbox.send_due(c) == 3
    assert sent_texts(routes) == ["a", "b", "c"]
