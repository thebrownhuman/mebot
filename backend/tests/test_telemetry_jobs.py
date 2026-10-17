import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from mebot.config import Settings
from mebot.main import create_app
from mebot.models import Bot
from mebot.repos import bots
from mebot.telemetry import service
from mebot.telemetry.service import Telemetry
from tests.conftest import ADMIN_EMAIL, do_setup

BASE = "https://registry.example.test"
T0 = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)
LATEST = {
    "latest": "0.10.1",
    "min_supported": "0.8.0",
    "advisories": [
        {"id": "A-1", "severity": "high", "affected": "<0.10.1", "title": "Fix", "url": None}
    ],
}


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        mode="single",
        data_dir=tmp_path,
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        ollama_host="http://ollama.invalid",
        telegram_workers=False,
        telemetry_workers=False,
        telemetry="on",
        registry_url=BASE,
        public_url="https://bot.example.dev",
        frontend_dist=tmp_path / "dist",
        github_token=None,
    )


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def env(settings, clock):
    """An app with setup done, plus a Telemetry on a frozen clock and a fixed jitter."""
    app = create_app(settings)
    with TestClient(app) as c:
        assert do_setup(c).status_code == 201
        tele = Telemetry(settings, app.state.session_factory, app.state.install_key, clock=clock)
        tele.rng = lambda: 0.5  # zero jitter
        yield app, tele


@pytest.fixture
def routes():
    with respx.mock(assert_all_called=False) as m:
        yield {
            "hb": m.post(f"{BASE}/v1/heartbeat").mock(return_value=httpx.Response(204)),
            "reg": m.post(f"{BASE}/v1/register").mock(return_value=httpx.Response(201, json={})),
            "del": m.delete(f"{BASE}/v1/register").mock(return_value=httpx.Response(204)),
            "latest": m.get(f"{BASE}/v1/latest").mock(
                return_value=httpx.Response(200, json=LATEST)
            ),
            "mock": m,
        }


def set_bot(app, **values):
    with app.state.session_factory() as db:
        bot = bots.get_primary(db)
        for k, v in values.items():
            setattr(bot, k, v)
        db.commit()


def state(app):
    with app.state.session_factory() as db:
        st = service.get_state(db)
        db.expunge(st)
        return st


def status(app, tele):
    with app.state.session_factory() as db:
        return tele.status(db, bots.get_primary(db))


# --- TELEMETRY=off ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_off_makes_no_requests_at_all(settings, clock, monkeypatch):
    settings.telemetry = "off"
    app = create_app(settings)

    def boom(*a, **k):
        raise AssertionError("an HTTP client was created with TELEMETRY=off")

    monkeypatch.setattr(httpx, "AsyncClient", boom)
    monkeypatch.setattr(httpx, "Client", boom)
    with TestClient(app) as c, respx.mock(assert_all_called=False) as m:
        assert do_setup(c, registration_consent=True).status_code == 201
        catch_all = m.route().mock(return_value=httpx.Response(200))
        tele = Telemetry(settings, app.state.session_factory, app.state.install_key, clock=clock)
        clock.now = T0 + timedelta(days=3)
        await tele.run_due()
        await app.state.telemetry.run_due()
        assert not catch_all.called and len(m.calls) == 0
        assert status(app, tele) == "off"


def test_off_schedules_no_background_job(settings):
    settings.telemetry = "off"
    settings.telemetry_workers = True
    app = create_app(settings)
    assert app.state.telemetry.enabled is False
    with TestClient(app):
        pass  # starting and stopping the app must not touch the network


# --- heartbeat ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_heartbeat_five_minutes_after_startup(env, routes, clock):
    app, tele = env
    clock.now = T0 + timedelta(minutes=4, seconds=59)
    await tele.run_due()
    assert not routes["hb"].called
    clock.now = T0 + timedelta(minutes=5)
    await tele.run_due()
    assert routes["hb"].call_count == 1 and routes["latest"].call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rng", "hours"), [(0.0, 23), (0.5, 24), (1.0, 25), (0.25, 23.5), (0.75, 24.5)]
)
async def test_next_heartbeat_is_24h_plus_minus_one_hour(env, routes, clock, rng, hours):
    app, tele = env
    tele.rng = lambda: rng
    clock.now = T0 + timedelta(minutes=5)
    await tele.run_due()
    assert tele.next_heartbeat_at == clock.now + timedelta(hours=hours)
    clock.now = tele.next_heartbeat_at - timedelta(seconds=1)
    await tele.run_due()
    assert routes["hb"].call_count == 1
    clock.now = tele.next_heartbeat_at
    await tele.run_due()
    assert routes["hb"].call_count == 2


@pytest.mark.asyncio
async def test_heartbeat_payload_is_stored_literally(env, routes, clock):
    app, tele = env
    clock.now = T0 + timedelta(minutes=5)
    await tele.run_due()
    st = state(app)
    sent = json.loads(routes["hb"].calls[0].request.content)
    assert json.loads(st.last_heartbeat_payload) == sent
    assert set(sent) == {"install_id", "public_key", "version", "mode"}
    assert st.last_heartbeat_at == clock.now


@pytest.mark.asyncio
async def test_heartbeat_is_sent_without_consent_and_registers_nothing(env, routes, clock):
    app, tele = env
    set_bot(app, registration_consent=False)
    clock.now = T0 + timedelta(minutes=5)
    await tele.run_due()
    assert routes["hb"].called and not routes["reg"].called


@pytest.mark.asyncio
async def test_failures_are_silent_and_retried_the_next_day(env, routes, clock):
    app, tele = env
    routes["hb"].mock(side_effect=httpx.ConnectError("dns"))
    routes["latest"].mock(side_effect=httpx.ConnectError("dns"))
    clock.now = T0 + timedelta(minutes=5)
    await tele.run_due()  # must not raise
    st = state(app)
    assert st.last_heartbeat_at is None and st.last_check_at is None
    assert tele.next_heartbeat_at == clock.now + timedelta(hours=24)
    clock.now += timedelta(hours=23, minutes=59)
    await tele.run_due()
    assert routes["hb"].call_count == 1


@pytest.mark.asyncio
async def test_a_hostile_registry_response_never_escapes(env, routes, clock):
    app, tele = env
    routes["latest"].mock(return_value=httpx.Response(200, content=b"x" * 100_000))
    routes["hb"].mock(return_value=httpx.Response(500, text="boom"))
    clock.now = T0 + timedelta(minutes=5)
    await tele.run_due()
    assert state(app).latest_version is None


# --- update check -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_check_stores_latest_and_advisories(env, routes, clock):
    app, tele = env
    clock.now = T0 + timedelta(minutes=5)
    await tele.run_due()
    st = state(app)
    assert st.latest_version == "0.10.1" and st.min_supported == "0.8.0"
    assert json.loads(st.advisories)[0]["id"] == "A-1"
    assert st.last_check_at == clock.now


@pytest.mark.asyncio
async def test_a_bad_latest_response_keeps_the_previous_answer(env, routes, clock):
    app, tele = env
    clock.now = T0 + timedelta(minutes=5)
    await tele.run_due()
    routes["latest"].mock(return_value=httpx.Response(200, json={"latest": "banana"}))
    clock.now = tele.next_heartbeat_at
    await tele.run_due()
    assert state(app).latest_version == "0.10.1"


def info(app, tele, version="0.9.0"):
    with app.state.session_factory() as db:
        return service.update_info(service.get_state(db), bots.get_primary(db), version)


@pytest.mark.asyncio
async def test_update_info_and_advisory_matching(env, routes, clock):
    app, tele = env
    clock.now = T0 + timedelta(minutes=5)
    await tele.run_due()
    old = info(app, tele, "0.9.0")
    assert old["available"] and old["latest"] == "0.10.1" and old["advisory"]["id"] == "A-1"
    assert not old["dismissed"] and not old["unsupported"]
    current = info(app, tele, "0.10.1")
    assert not current["available"] and current["advisory"] is None
    assert info(app, tele, "0.10.1-dev")["available"] is False
    assert info(app, tele, "0.7.0")["unsupported"] is True


@pytest.mark.asyncio
async def test_dismissed_update_is_hidden_until_a_newer_version(env, routes, clock):
    app, tele = env
    clock.now = T0 + timedelta(minutes=5)
    await tele.run_due()
    set_bot(app, dismissed_update_version="0.10.1")
    assert info(app, tele)["dismissed"] is True
    routes["latest"].mock(return_value=httpx.Response(200, json={**LATEST, "latest": "0.11.0"}))
    clock.now = tele.next_heartbeat_at
    await tele.run_due()
    assert info(app, tele)["dismissed"] is False


# --- registration -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registers_once_with_the_admin_email_and_public_url(env, routes, clock):
    app, tele = env
    set_bot(app, registration_consent=True)
    await tele.run_due()
    assert routes["reg"].call_count == 1
    assert json.loads(routes["reg"].calls[0].request.content)["email"] == ADMIN_EMAIL
    assert (
        json.loads(routes["reg"].calls[0].request.content)["site_url"] == "https://bot.example.dev"
    )
    assert status(app, tele) == "registered"
    assert state(app).registered_at == clock.now
    await tele.run_due()
    clock.now += timedelta(hours=1)
    await tele.run_due()
    assert routes["reg"].call_count == 1  # not again


@pytest.mark.asyncio
async def test_no_consent_no_registration(env, routes):
    app, tele = env
    await tele.run_due()
    assert not routes["reg"].called and not routes["del"].called
    assert status(app, tele) == "not_registered"


@pytest.mark.asyncio
async def test_waits_for_public_url_then_registers(env, routes, settings):
    app, tele = env
    set_bot(app, registration_consent=True)
    settings.public_url = None
    await tele.run_due()
    assert not routes["reg"].called and status(app, tele) == "waiting_for_public_url"
    settings.public_url = "https://bot.example.dev"
    await tele.run_due()
    assert routes["reg"].call_count == 1 and status(app, tele) == "registered"


@pytest.mark.asyncio
async def test_contact_email_overrides_the_admin_email_and_reregisters(env, routes):
    app, tele = env
    set_bot(app, registration_consent=True)
    await tele.run_due()
    set_bot(app, update_contact_email="updates@acme.dev")
    assert status(app, tele) == "pending"
    await tele.run_due()
    assert routes["reg"].call_count == 2
    assert json.loads(routes["reg"].calls[1].request.content)["email"] == "updates@acme.dev"
    assert status(app, tele) == "registered"


@pytest.mark.asyncio
async def test_site_change_reregisters(env, routes, settings):
    app, tele = env
    set_bot(app, registration_consent=True)
    await tele.run_due()
    settings.public_url = "https://new.example.dev"
    await tele.run_due()
    assert routes["reg"].call_count == 2


@pytest.mark.asyncio
async def test_major_version_change_reregisters_but_minor_does_not(env, routes):
    app, tele = env
    set_bot(app, registration_consent=True)
    await tele.run_due()
    tele.version = "0.10.0"
    await tele.run_due()
    assert routes["reg"].call_count == 1
    tele.version = "1.0.0"
    await tele.run_due()
    assert routes["reg"].call_count == 2


@pytest.mark.asyncio
async def test_registration_failure_is_recorded_and_retried_after_ten_minutes(env, routes, clock):
    app, tele = env
    set_bot(app, registration_consent=True)
    routes["reg"].mock(return_value=httpx.Response(503, json={"error": {"code": "DOWN"}}))
    await tele.run_due()
    st = state(app)
    assert "DOWN" in st.last_register_error and st.registered_at is None
    assert status(app, tele) == "pending"
    clock.now += timedelta(minutes=9)
    await tele.run_due()
    assert routes["reg"].call_count == 1
    routes["reg"].mock(return_value=httpx.Response(201, json={}))
    clock.now += timedelta(minutes=1)
    await tele.run_due()
    assert routes["reg"].call_count == 2
    assert state(app).last_register_error is None and status(app, tele) == "registered"


@pytest.mark.asyncio
async def test_nudge_retries_immediately(env, routes, clock):
    app, tele = env
    set_bot(app, registration_consent=True)
    routes["reg"].mock(side_effect=httpx.ConnectError("down"))
    await tele.run_due()
    routes["reg"].mock(return_value=httpx.Response(201, json={}))
    await tele.run_due()
    assert routes["reg"].call_count == 1  # still backing off
    tele.nudge()
    await tele.run_due()
    assert routes["reg"].call_count == 2


# --- unregistration -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoking_consent_deletes_the_registration(env, routes):
    app, tele = env
    set_bot(app, registration_consent=True)
    await tele.run_due()
    set_bot(app, registration_consent=False)
    await tele.run_due()
    assert routes["del"].call_count == 1
    st = state(app)
    assert st.registered_at is None and st.registered_fingerprint is None
    assert st.unregister_pending is False
    assert status(app, tele) == "not_registered"
    await tele.run_due()
    assert routes["del"].call_count == 1  # done; not again


@pytest.mark.asyncio
async def test_unregister_is_retried_until_it_succeeds(env, routes, clock):
    app, tele = env
    set_bot(app, registration_consent=True)
    await tele.run_due()
    set_bot(app, registration_consent=False)
    routes["del"].mock(side_effect=httpx.ConnectError("down"))
    await tele.run_due()
    assert status(app, tele) == "unregister_pending"
    for _ in range(3):
        clock.now += timedelta(minutes=10)
        await tele.run_due()
    assert routes["del"].call_count == 4 and status(app, tele) == "unregister_pending"
    routes["del"].mock(return_value=httpx.Response(204))
    clock.now += timedelta(minutes=10)
    await tele.run_due()
    assert status(app, tele) == "not_registered" and state(app).unregister_pending is False


@pytest.mark.asyncio
async def test_pending_unregister_survives_a_restart(env, routes, clock, settings):
    app, tele = env
    set_bot(app, registration_consent=True)
    await tele.run_due()
    set_bot(app, registration_consent=False)
    routes["del"].mock(side_effect=httpx.ConnectError("down"))
    await tele.run_due()
    fresh = Telemetry(settings, app.state.session_factory, app.state.install_key, clock=clock)
    routes["del"].mock(return_value=httpx.Response(204))
    await fresh.run_due()
    assert status(app, fresh) == "not_registered"


@pytest.mark.asyncio
async def test_opting_back_in_cancels_a_pending_unregister(env, routes):
    app, tele = env
    set_bot(app, registration_consent=True)
    await tele.run_due()
    set_bot(app, registration_consent=False)
    routes["del"].mock(side_effect=httpx.ConnectError("down"))
    await tele.run_due()
    set_bot(app, registration_consent=True)
    tele.nudge()
    await tele.run_due()
    assert status(app, tele) in ("registered", "pending")
    assert routes["del"].call_count == 1
    assert state(app).unregister_pending is False


@pytest.mark.asyncio
async def test_unknown_install_on_delete_counts_as_done(env, routes):
    app, tele = env
    set_bot(app, registration_consent=True)
    await tele.run_due()
    set_bot(app, registration_consent=False)
    routes["del"].mock(
        return_value=httpx.Response(
            401, json={"error": {"code": "UNKNOWN_INSTALL", "message": "x"}}
        )
    )
    await tele.run_due()
    assert status(app, tele) == "not_registered"


@pytest.mark.asyncio
async def test_never_registered_and_no_consent_sends_no_delete(env, routes):
    app, tele = env
    set_bot(app, registration_consent=False)
    await tele.run_due()
    assert not routes["del"].called


# --- misc ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idle_without_a_usable_install_key(settings, clock, routes):
    app = create_app(settings)
    with TestClient(app) as c:
        do_setup(c, registration_consent=True)
        tele = Telemetry(settings, app.state.session_factory, None, clock=clock)
        clock.now = T0 + timedelta(days=2)
        await tele.run_due()
        assert not routes["hb"].called and not routes["reg"].called
        with app.state.session_factory() as db:
            assert tele.status(db, bots.get_primary(db)) == "unavailable"


def test_status_values_cover_the_account_states(env, settings):
    app, tele = env
    assert status(app, tele) == "not_registered"
    set_bot(app, registration_consent=True)
    assert status(app, tele) == "pending"
    settings.public_url = ""
    assert status(app, tele) == "waiting_for_public_url"


def test_bot_columns_exist():
    assert hasattr(Bot, "update_contact_email") and hasattr(Bot, "dismissed_update_version")
