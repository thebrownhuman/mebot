import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from mebot.models import AccessLog, Bot
from mebot.repos import bots
from mebot.telemetry import service
from tests.conftest import ADMIN_EMAIL, csrf

URL = "/api/admin/telemetry"
NOW = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)


def put(c, **body):
    return c.put(URL, json=body, headers=csrf(c))


def seed_state(app, **values):
    with app.state.session_factory() as db:
        st = service.get_state(db)
        for k, v in values.items():
            setattr(st, k, v)
        db.commit()


def test_requires_login(client):
    assert client.get(URL).status_code in (401, 503)


def test_get_default_view(admin_client, app):
    r = admin_client.get(URL)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["telemetry"] == "on" and b["registry_url"] == "https://registry.shivanshmishra.in"
    assert b["consent"] is False and b["status"] == "not_registered"
    assert b["registered_at"] is None and b["last_heartbeat"] is None
    assert len(b["install_id_prefix"]) == 8
    assert b["install_id_prefix"] == app.state.install_key.install_id[:8]
    assert b["effective_email"] == ADMIN_EMAIL and b["update_contact_email"] is None
    assert b["payload_preview"] == {
        "install_id": app.state.install_key.install_id,
        "public_key": app.state.install_key.public_b64,
        "version": "0.9.0",
        "mode": "single",
    }
    assert b["update"] == {
        "current": "0.9.0",
        "latest": None,
        "available": False,
        "dismissed": False,
        "unsupported": False,
        "advisory": None,
    }


def test_never_exposes_the_full_install_id_or_key_material(admin_client, app):
    key = app.state.install_key
    seed = (app.state.settings.data_dir / "install.key").read_text().strip()
    # the literal payload preview deliberately shows what is sent; nothing else may leak
    body = admin_client.get(URL).json()
    body.pop("payload_preview")
    text = json.dumps(body)
    assert key.install_id not in text and seed not in text


def test_put_consent_roundtrip_and_audit(admin_client, app):
    r = put(admin_client, consent=True)
    assert r.status_code == 200 and r.json()["consent"] is True
    with app.state.session_factory() as db:
        assert bots.get_primary(db).registration_consent is True
        assert (
            db.scalar(select(AccessLog.detail).where(AccessLog.event == "telemetry_updated"))
            == "consent"
        )
    assert put(admin_client, consent=False).json()["consent"] is False


def test_put_nudges_the_worker(admin_client, app):
    app.state.telemetry.next_retry_at = datetime(2999, 1, 1, tzinfo=UTC)
    put(admin_client, consent=True)
    assert app.state.telemetry.next_retry_at is None


def test_unchanged_put_does_not_log_or_nudge(admin_client, app):
    app.state.telemetry.next_retry_at = datetime(2999, 1, 1, tzinfo=UTC)
    put(admin_client, consent=False)
    assert app.state.telemetry.next_retry_at is not None
    with app.state.session_factory() as db:
        assert db.scalar(select(AccessLog.id).where(AccessLog.event == "telemetry_updated")) is None


def test_contact_email_set_clear_and_normalised(admin_client, app):
    r = put(admin_client, update_contact_email="  Updates@Acme.DEV ")
    assert r.json()["update_contact_email"] == "Updates@acme.dev"
    assert r.json()["effective_email"] == "Updates@acme.dev"
    r = put(admin_client, update_contact_email="")
    assert r.json()["update_contact_email"] is None and r.json()["effective_email"] == ADMIN_EMAIL
    put(admin_client, update_contact_email="x@y.dev")
    assert put(admin_client, update_contact_email=None).json()["update_contact_email"] is None


@pytest.mark.parametrize("bad", ["nope", "a@b", "a b@c.dev", "x" * 260 + "@a.dev"])
def test_contact_email_validation(admin_client, bad):
    assert put(admin_client, update_contact_email=bad).status_code == 422


def test_put_only_touches_the_fields_sent(admin_client, app):
    put(admin_client, consent=True, update_contact_email="a@b.dev")
    put(admin_client, consent=False)
    with app.state.session_factory() as db:
        bot = bots.get_primary(db)
        assert bot.update_contact_email == "a@b.dev" and bot.registration_consent is False


@pytest.mark.parametrize("body", [{"unknown": 1}, {"consent": "maybe"}])
def test_put_validation(admin_client, body):
    assert put(admin_client, **body).status_code == 422


def test_mutations_need_csrf(admin_client):
    assert admin_client.put(URL, json={"consent": True}).status_code == 403
    assert admin_client.post(f"{URL}/dismiss-update", json={"version": "1.0.0"}).status_code == 403


def test_status_reflects_the_server_state(admin_client, app):
    settings = app.state.settings
    put(admin_client, consent=True)
    assert admin_client.get(URL).json()["status"] == "waiting_for_public_url"
    settings.public_url = "https://bot.example.dev"
    assert admin_client.get(URL).json()["status"] == "pending"
    seed_state(
        app,
        registered_at=NOW,
        registered_fingerprint=f"{ADMIN_EMAIL}|https://bot.example.dev|0",
    )
    b = admin_client.get(URL).json()
    assert b["status"] == "registered" and b["registered_at"] == "2026-10-17T10:00:00Z"
    assert b["public_url"] == "https://bot.example.dev"
    settings.public_url = None
    assert admin_client.get(URL).json()["status"] == "waiting_for_public_url"


def test_status_off_by_server_setting(admin_client, app):
    app.state.settings.telemetry = "off"
    b = admin_client.get(URL).json()
    assert b["telemetry"] == "off" and b["status"] == "off"
    assert put(admin_client, consent=True).status_code == 200  # stored, but inert


def test_old_update_info_is_hidden_when_telemetry_is_off(admin_client, app):
    seed_state(
        app,
        latest_version="0.10.1",
        advisories=json.dumps([{"id": "A", "affected": "<0.10.1", "title": "t"}]),
    )
    assert admin_client.get(URL).json()["update"]["advisory"]["id"] == "A"
    app.state.settings.telemetry = "off"
    u = admin_client.get(URL).json()["update"]
    assert u["available"] is False and u["advisory"] is None


def test_last_heartbeat_and_error_are_shown(admin_client, app):
    payload = {"install_id": "x" * 32, "public_key": "k", "version": "0.9.0", "mode": "single"}
    seed_state(
        app,
        last_heartbeat_at=NOW,
        last_heartbeat_payload=json.dumps(payload),
        last_check_at=NOW,
        last_register_error="http: BAD",
    )
    b = admin_client.get(URL).json()
    assert b["last_heartbeat"] == {"sent_at": "2026-10-17T10:00:00Z", "payload": payload}
    assert b["last_check_at"] == "2026-10-17T10:00:00Z" and b["last_register_error"] == "http: BAD"


def test_update_and_advisory_in_the_view(admin_client, app):
    seed_state(
        app,
        latest_version="0.10.1",
        min_supported="0.8.0",
        advisories=json.dumps(
            [
                {
                    "id": "A-1",
                    "severity": "high",
                    "affected": "<0.10.1",
                    "title": "Fix",
                    "url": "https://ex.test/a",
                }
            ]
        ),
    )
    u = admin_client.get(URL).json()["update"]
    assert u["available"] and u["latest"] == "0.10.1" and not u["dismissed"]
    assert u["advisory"] == {
        "id": "A-1",
        "severity": "high",
        "title": "Fix",
        "url": "https://ex.test/a",
    }


def test_dismiss_update(admin_client, app):
    seed_state(app, latest_version="0.10.1")
    r = admin_client.post(
        f"{URL}/dismiss-update", json={"version": "0.10.1"}, headers=csrf(admin_client)
    )
    assert r.status_code == 204
    assert admin_client.get(URL).json()["update"]["dismissed"] is True
    with app.state.session_factory() as db:
        assert db.scalar(select(Bot.dismissed_update_version)) == "0.10.1"
    seed_state(app, latest_version="0.11.0")  # a newer release shows again
    assert admin_client.get(URL).json()["update"]["dismissed"] is False


@pytest.mark.parametrize("bad", ["", "latest", "1.2", "x" * 50])
def test_dismiss_validation(admin_client, bad):
    r = admin_client.post(
        f"{URL}/dismiss-update", json={"version": bad}, headers=csrf(admin_client)
    )
    assert r.status_code == 422


def test_advisory_is_not_dismissible_via_the_api(admin_client, app):
    seed_state(
        app,
        latest_version="0.10.1",
        advisories=json.dumps([{"id": "A", "affected": "<0.10.1", "title": "t"}]),
    )
    admin_client.post(
        f"{URL}/dismiss-update", json={"version": "0.10.1"}, headers=csrf(admin_client)
    )
    u = admin_client.get(URL).json()["update"]
    assert u["dismissed"] is True and u["advisory"]["id"] == "A"  # the UI must still show it
