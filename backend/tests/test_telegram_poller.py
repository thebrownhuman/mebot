import asyncio
from datetime import timedelta

import httpx
import respx
from sqlalchemy import select

from mebot.models import AccessLog, TelegramConfig, utcnow
from mebot.telegram import poller, repo
from tests.tg_helpers import BASE, ctx, link, mock_telegram, ok, sent_texts, text_update


def cfg(app) -> TelegramConfig:
    with app.state.session_factory() as db:
        return db.scalar(select(TelegramConfig))


def test_backoff_doubles_to_60():
    seq, b = [], 0.0
    for _ in range(9):
        b = poller.next_backoff(b)
        seq.append(b)
    assert seq == [1, 2, 4, 8, 16, 32, 60, 60, 60]


@respx.mock
async def test_processes_in_order_and_persists_offset(admin_client, app):
    routes = mock_telegram()
    bot_id = link(app)
    u1, u2 = text_update("/help"), text_update("/help")
    route = respx.post(f"{BASE}/getUpdates").mock(return_value=ok([u2, u1]))
    assert await poller.poll_once(ctx(app), bot_id, "p1") == "ok"
    assert cfg(app).last_update_id == u2["update_id"]
    assert len(routes["sendMessage"].calls) == 2
    await poller.poll_once(ctx(app), bot_id, "p1")
    import json

    assert json.loads(route.calls.last.request.content)["offset"] == u2["update_id"] + 1


@respx.mock
async def test_lease_prevents_second_poller(admin_client, app):
    mock_telegram()
    bot_id = link(app)
    assert await poller.poll_once(ctx(app), bot_id, "proc-A") == "ok"
    assert await poller.poll_once(ctx(app), bot_id, "proc-B") == "no_lease"
    # an expired lease can be taken over (crashed holder)
    later = ctx(app, now=lambda: utcnow() + timedelta(minutes=5))
    assert await poller.poll_once(later, bot_id, "proc-B") == "ok"
    assert cfg(app).lease_owner == "proc-B"


def test_lease_cas(admin_client, app):
    bot_id = link(app)
    ttl = timedelta(seconds=60)
    with app.state.session_factory() as db:
        assert repo.try_lease(db, bot_id, "A", ttl)
        assert repo.try_lease(db, bot_id, "A", ttl)  # heartbeat renew
        assert not repo.try_lease(db, bot_id, "B", ttl)
        repo.release_lease(db, bot_id, "A")
        assert repo.try_lease(db, bot_id, "B", ttl)


@respx.mock
async def test_401_stops_and_marks_error_once(admin_client, app):
    mock_telegram()
    bot_id = link(app)
    respx.post(f"{BASE}/getUpdates").mock(
        return_value=httpx.Response(401, json={"ok": False, "error_code": 401})
    )
    assert await poller.poll_once(ctx(app), bot_id, "p") == "auth"
    assert await poller.poll_once(ctx(app), bot_id, "p") == "auth"
    assert "rejected" in cfg(app).error
    with app.state.session_factory() as db:
        n = len(
            db.scalars(select(AccessLog).where(AccessLog.event == "TELEGRAM_AUTH_FAILED")).all()
        )
    assert n == 1
    assert admin_client.get("/api/admin/telegram").json()["error"]


@respx.mock
async def test_error_returns_error_and_inactive_without_token(admin_client, app):
    mock_telegram()
    bot_id = link(app)
    respx.post(f"{BASE}/getUpdates").mock(side_effect=httpx.ConnectError("down"))
    assert await poller.poll_once(ctx(app), bot_id, "p") == "error"
    with app.state.session_factory() as db:
        repo.forget(db, repo.get(db, bot_id))
        db.commit()
    assert await poller.poll_once(ctx(app), bot_id, "p") == "inactive"


@respx.mock
async def test_run_poller_stops_cleanly_and_releases_lease(admin_client, app):
    mock_telegram()
    bot_id = link(app)

    async def slow_updates(request):
        await asyncio.sleep(0.01)
        return ok([])

    respx.post(f"{BASE}/getUpdates").mock(side_effect=slow_updates)
    stop = asyncio.Event()
    task = asyncio.create_task(poller.run_poller(ctx(app), bot_id, "p", stop))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, 2)
    assert cfg(app).lease_owner is None


# --- webhook ----------------------------------------------------------------------


def _webhook_ready(app):
    return link(app, mode="webhook", webhook_secret="s3cr3t-hook")


@respx.mock
def test_webhook_secret_verified(admin_client, app):
    routes = mock_telegram()
    bot_id = _webhook_ready(app)
    url = f"/api/telegram/webhook/{bot_id}"
    upd = text_update("/help")
    assert admin_client.post(url, json=upd).status_code == 403
    bad = {"X-Telegram-Bot-Api-Secret-Token": "nope"}
    assert admin_client.post(url, json=upd, headers=bad).status_code == 403
    good = {"X-Telegram-Bot-Api-Secret-Token": "s3cr3t-hook"}
    assert admin_client.post(url, json=upd, headers=good).status_code == 200
    assert len(sent_texts(routes)) == 1
    # Telegram redelivery of the same update is ignored
    admin_client.post(url, json=upd, headers=good)
    assert len(sent_texts(routes)) == 1


def test_webhook_403_in_polling_mode_or_unknown_bot(admin_client, app):
    bot_id = link(app, webhook_secret="x")
    h = {"X-Telegram-Bot-Api-Secret-Token": "x"}
    assert (
        admin_client.post(f"/api/telegram/webhook/{bot_id}", json={}, headers=h).status_code == 403
    )
    assert admin_client.post("/api/telegram/webhook/nope", json={}, headers=h).status_code == 403


@respx.mock
def test_lifespan_starts_and_stops_workers(settings):
    from fastapi.testclient import TestClient

    from mebot.main import create_app

    mock_telegram()
    settings.telegram_workers = True
    app = create_app(settings)
    with TestClient(app):
        assert app.state.telegram.running
        assert app.state.telegram._tasks
    assert not app.state.telegram.running and not app.state.telegram._tasks


def test_workers_off_in_tests(app, client):
    assert app.state.telegram.running is False
