import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app import notify
from tests.conftest import rows
from tests.helpers import NOW, Install

SEND = "https://api.telegram.org/bot123:TOKEN/sendMessage"
UPDATES = "https://api.telegram.org/bot123:TOKEN/getUpdates"


def register(client, inst=None, **over):
    inst = inst or Install()
    return inst, inst.post(client, "/v1/register", inst.register_body(**over))


def notes(app):
    return rows(app, "SELECT * FROM notifications ORDER BY rowid")


async def deliver(app, now=NOW):
    async with httpx.AsyncClient() as c:
        return await notify.send_due(app.state.db, app.state.settings, c, now)


class TestEnqueueOnRegistration:
    def test_new_registration_queues_a_ping(self, client, app):
        register(client, email="priya@acme.dev", site_url="https://priya.dev")
        [n] = notes(app)
        assert n["status"] == "pending" and n["kind"] == "registration_new"
        assert n["text"] == "🆕 mebot install — priya@acme.dev · https://priya.dev · v0.9.0"

    def test_email_and_site_are_html_escaped(self, client, app):
        register(client, site_url="https://x.example/?a=<b>&c=1")
        assert "&lt;b&gt;&amp;c=1" in notes(app)[0]["text"]
        assert "<b>" not in notes(app)[0]["text"]

    def test_changed_email_or_site_pings_as_updated(self, client, app):
        inst, _ = register(client)
        inst.post(
            client,
            "/v1/register",
            inst.register_body(email="new@acme.dev"),
            at=NOW + timedelta(seconds=1),
        )
        kinds = [n["kind"] for n in notes(app)]
        assert kinds == ["registration_new", "registration_updated"]
        assert notes(app)[1]["text"].startswith("✏️ mebot registration updated — new@acme.dev")

    def test_version_only_reregister_does_not_ping(self, client, app):
        inst, _ = register(client)
        inst.post(
            client,
            "/v1/register",
            inst.register_body(version="0.10.0"),
            at=NOW + timedelta(seconds=1),
        )
        assert len(notes(app)) == 1

    def test_heartbeats_and_deletes_never_ping(self, client, app):
        inst, _ = register(client)
        inst.post(client, "/v1/heartbeat", inst.heartbeat_body(), at=NOW + timedelta(seconds=1))
        inst.delete(client, "/v1/register", at=NOW + timedelta(seconds=2))
        assert len(notes(app)) == 1

    def test_registration_still_stored_when_telegram_is_not_configured(self, settings, clock):
        from fastapi.testclient import TestClient

        from app.main import create_app

        settings.telegram_bot_token = ""
        app = create_app(settings, clock)
        with TestClient(app) as c:
            _, r = register(c)
            assert r.status_code == 201
        assert notes(app) == [] and len(rows(app, "SELECT * FROM registrations")) == 1


@pytest.mark.asyncio
class TestDelivery:
    @respx.mock
    async def test_sends_html_to_the_maintainer_chat(self, client, app):
        route = respx.post(SEND).mock(return_value=httpx.Response(200, json={"ok": True}))
        register(client)
        assert await deliver(app) == 1
        sent = json.loads(route.calls[0].request.content)
        assert sent["chat_id"] == "777" and sent["parse_mode"] == "HTML"
        assert sent["text"].startswith("🆕 mebot install")
        assert notes(app)[0]["status"] == "sent"
        assert await deliver(app) == 0  # nothing left

    @respx.mock
    async def test_failure_backs_off_and_retries(self, client, app):
        route = respx.post(SEND).mock(return_value=httpx.Response(502))
        register(client)
        assert await deliver(app, NOW) == 0
        [n] = notes(app)
        assert n["status"] == "pending" and n["attempts"] == 1
        assert n["next_attempt_at"] == "2026-10-17T10:01:00Z"  # 30s * 2^1
        assert await deliver(app, NOW + timedelta(seconds=30)) == 0  # not due yet
        assert route.call_count == 1
        route.mock(return_value=httpx.Response(200, json={"ok": True}))
        assert await deliver(app, NOW + timedelta(seconds=61)) == 1
        assert notes(app)[0]["status"] == "sent"

    @respx.mock
    async def test_network_errors_are_retried(self, client, app):
        respx.post(SEND).mock(side_effect=httpx.ConnectError("down"))
        register(client)
        await deliver(app)
        assert (
            notes(app)[0]["status"] == "pending" and notes(app)[0]["last_error"] == "ConnectError"
        )

    @respx.mock
    async def test_honours_retry_after(self, client, app):
        respx.post(SEND).mock(
            return_value=httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 120}})
        )
        register(client)
        await deliver(app)
        [n] = notes(app)
        assert n["status"] == "pending" and n["next_attempt_at"] == "2026-10-17T10:02:00Z"

    @respx.mock
    async def test_dead_after_repeated_failures(self, client, app):
        respx.post(SEND).mock(return_value=httpx.Response(500))
        register(client)
        when = NOW
        for _ in range(notify.MAX_ATTEMPTS):
            await deliver(app, when)
            when += timedelta(hours=2)
        [n] = notes(app)
        assert n["status"] == "dead" and n["attempts"] == notify.MAX_ATTEMPTS

    @respx.mock
    async def test_bad_token_or_chat_is_dead_at_once(self, client, app):
        respx.post(SEND).mock(
            return_value=httpx.Response(400, json={"ok": False, "description": "chat not found"})
        )
        register(client)
        await deliver(app)
        assert notes(app)[0]["status"] == "dead"
        assert "chat not found" in notes(app)[0]["last_error"]

    @respx.mock
    async def test_one_failure_does_not_block_the_others(self, client, app):
        calls = {"n": 0}

        def flaky(request):
            calls["n"] += 1
            return (
                httpx.Response(500) if calls["n"] == 1 else httpx.Response(200, json={"ok": True})
            )

        respx.post(SEND).mock(side_effect=flaky)
        register(client)
        register(client)
        assert await deliver(app) == 1

    async def test_does_nothing_without_telegram_config(self, client, app, settings):
        register(client)
        settings.telegram_bot_token = ""
        with respx.mock(assert_all_called=False) as m:
            route = m.post(SEND)
            assert await deliver(app) == 0
            assert not route.called


class TestWeeklySummary:
    MON_9 = datetime(2026, 10, 19, 3, 30, tzinfo=UTC)  # Monday 09:00 in Asia/Kolkata

    def seed(self, client):
        a, b = Install(), Install()
        a.post(client, "/v1/heartbeat", a.heartbeat_body(version="0.9.0"))
        b.post(client, "/v1/heartbeat", b.heartbeat_body(version="0.8.0"))
        register(client)

    def test_queued_once_on_monday_after_nine_local(self, client, app, settings):
        self.seed(client)
        db = app.state.db
        before = len(notes(app))
        assert not notify.maybe_weekly_summary(db, settings, self.MON_9 - timedelta(minutes=1))
        assert notify.maybe_weekly_summary(db, settings, self.MON_9)
        assert not notify.maybe_weekly_summary(db, settings, self.MON_9 + timedelta(hours=5))
        new = notes(app)[before:]
        assert len(new) == 1 and new[0]["kind"] == "weekly"
        text = new[0]["text"]
        assert "mebot weekly — 2026-10-19" in text
        assert "Active installs: 3 (7 days) · 3 (30 days)" in text
        assert "Registrations: 1 (+1 this week)" in text
        assert "0.9.0 ×2, 0.8.0 ×1" in text

    def test_not_on_other_weekdays(self, client, app, settings):
        for day in range(20, 26):  # Tue..Sun
            assert not notify.maybe_weekly_summary(
                app.state.db, settings, datetime(2026, 10, day, 12, tzinfo=UTC)
            )

    def test_next_week_sends_again(self, client, app, settings):
        db = app.state.db
        assert notify.maybe_weekly_summary(db, settings, self.MON_9)
        assert notify.maybe_weekly_summary(db, settings, self.MON_9 + timedelta(days=7))

    def test_respects_the_configured_timezone(self, client, app, settings):
        settings.timezone = "America/New_York"
        # 09:00 IST Monday is still Sunday night in New York
        assert not notify.maybe_weekly_summary(app.state.db, settings, self.MON_9)
        assert notify.maybe_weekly_summary(
            app.state.db,
            settings,
            datetime(2026, 10, 19, 13, 0, tzinfo=UTC),  # 09:00 EDT
        )

    def test_unknown_timezone_falls_back_to_utc(self, client, app, settings):
        settings.timezone = "Mars/Olympus"
        assert notify.maybe_weekly_summary(
            app.state.db, settings, datetime(2026, 10, 19, 9, 0, tzinfo=UTC)
        )

    def test_no_summary_without_telegram(self, client, app, settings):
        settings.telegram_chat_id = ""
        assert not notify.maybe_weekly_summary(app.state.db, settings, self.MON_9)


def update(chat_id, text, uid=1):
    return {"update_id": uid, "message": {"chat": {"id": chat_id}, "text": text}}


class TestStatsCommand:
    def test_answers_the_maintainer_chat(self, client, app, settings):
        register(client)
        before = len(notes(app))
        assert notify.handle_update(app.state.db, settings, update(777, "/stats"), NOW)
        reply = notes(app)[before]
        assert reply["kind"] == "stats" and "mebot stats" in reply["text"]
        assert "Active installs: 1" in reply["text"]

    def test_accepts_the_bot_suffix(self, client, app, settings):
        assert notify.handle_update(
            app.state.db, settings, update(777, "/stats@my_registry_bot"), NOW
        )

    @pytest.mark.parametrize("chat", [111, -100777, 0])
    def test_ignores_every_other_chat(self, client, app, settings, chat):
        assert not notify.handle_update(app.state.db, settings, update(chat, "/stats"), NOW)
        assert notes(app) == []

    @pytest.mark.parametrize("text", ["hello", "/start", "/stats now please", ""])
    def test_ignores_other_text(self, client, app, settings, text):
        assert not notify.handle_update(app.state.db, settings, update(777, text), NOW)

    @pytest.mark.asyncio
    @respx.mock
    async def test_polling_answers_and_advances_the_offset(self, client, app, settings):
        first = {"ok": True, "result": [update(999, "/stats", 41), update(777, "/stats", 42)]}
        route = respx.post(UPDATES).mock(
            side_effect=[
                httpx.Response(200, json=first),
                httpx.Response(200, json={"ok": True, "result": []}),
            ]
        )
        async with httpx.AsyncClient() as c:
            assert await notify.poll_commands(app.state.db, settings, c, NOW) == 1
            await notify.poll_commands(app.state.db, settings, c, NOW)
        assert app.state.db.meta_get("telegram_offset") == "43"
        assert json.loads(route.calls[1].request.content)["offset"] == 43
        assert [n["kind"] for n in notes(app)] == ["stats"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_polling_survives_telegram_errors(self, client, app, settings):
        respx.post(UPDATES).mock(side_effect=httpx.ConnectError("down"))
        async with httpx.AsyncClient() as c:
            assert await notify.poll_commands(app.state.db, settings, c, NOW) == 0
