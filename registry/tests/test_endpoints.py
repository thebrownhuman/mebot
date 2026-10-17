import json
from datetime import timedelta

import pytest

from tests.conftest import RELEASES, rows
from tests.helpers import NOW, Install


def hb(client, inst, **over):
    return inst.post(client, "/v1/heartbeat", inst.heartbeat_body(**over))


def reg(client, inst, **over):
    return inst.post(client, "/v1/register", inst.register_body(**over))


def err(r) -> str:
    return r.json()["error"]["code"]


class TestHeartbeat:
    def test_first_heartbeat_pins_the_key_and_stores_no_network_data(self, client, app, install):
        r = hb(client, install)
        assert r.status_code == 204 and r.content == b""
        [row] = rows(app, "SELECT * FROM installs")
        assert row["install_id"] == install.install_id
        assert row["public_key"] == install.public_key
        assert row["version"] == "0.9.0" and row["mode"] == "single"
        assert row["first_seen"] == row["last_seen"] == "2026-10-17T10:00:00Z"
        assert set(row) == {
            "install_id",
            "public_key",
            "first_seen",
            "last_seen",
            "version",
            "mode",
        }

    def test_later_heartbeat_updates_last_seen_and_version(self, client, app, clock, install):
        hb(client, install)
        clock.now = NOW + timedelta(days=1)
        assert (
            install.post(
                client,
                "/v1/heartbeat",
                install.heartbeat_body(version="0.10.0", mode="hosted"),
                at=clock.now,
            ).status_code
            == 204
        )
        [row] = rows(app, "SELECT * FROM installs")
        assert row["first_seen"] == "2026-10-17T10:00:00Z"
        assert row["last_seen"] == "2026-10-18T10:00:00Z"
        assert row["version"] == "0.10.0" and row["mode"] == "hosted"

    def test_no_ip_or_hostname_is_stored_anywhere(self, client, app, install):
        client.headers["x-forwarded-for"] = "203.0.113.9"
        hb(client, install)
        reg(client, Install())
        dump = json.dumps(
            [
                rows(app, f"SELECT * FROM {t}")
                for t in ("installs", "registrations", "nonces", "meta")
            ]
        )
        assert "203.0.113.9" not in dump and "testclient" not in dump

    def test_signature_from_another_key_is_rejected(self, client, app, install):
        hb(client, install)
        other = Install()
        body = install.heartbeat_body()
        raw = json.dumps(body, separators=(",", ":")).encode()
        r = client.post(
            "/v1/heartbeat",
            content=raw,
            headers=other.headers("POST", "/v1/heartbeat", raw, install_id=install.install_id),
        )
        assert r.status_code == 401 and err(r) in ("SIGNATURE_INVALID", "KEY_MISMATCH")

    def test_body_key_cannot_replace_the_pinned_key(self, client, install):
        hb(client, install)
        attacker = Install()
        body = install.heartbeat_body(public_key=attacker.public_key)
        raw = json.dumps(body, separators=(",", ":")).encode()
        r = client.post(
            "/v1/heartbeat",
            content=raw,
            headers=attacker.headers("POST", "/v1/heartbeat", raw, install_id=install.install_id),
        )
        assert r.status_code == 401 and err(r) == "KEY_MISMATCH"

    def test_replayed_request_is_rejected(self, client, install):
        raw = json.dumps(install.heartbeat_body(), separators=(",", ":")).encode()
        headers = install.headers("POST", "/v1/heartbeat", raw)
        assert client.post("/v1/heartbeat", content=raw, headers=headers).status_code == 204
        r = client.post("/v1/heartbeat", content=raw, headers=headers)
        assert r.status_code == 401 and err(r) == "REPLAYED"

    def test_old_timestamp_is_rejected(self, client, install):
        r = install.post(
            client, "/v1/heartbeat", install.heartbeat_body(), at=NOW - timedelta(minutes=6)
        )
        assert r.status_code == 401 and err(r) == "TIMESTAMP_SKEW"

    def test_body_install_id_must_match_the_signing_key(self, client, install):
        other = Install()
        r = install.post(
            client, "/v1/heartbeat", install.heartbeat_body(install_id=other.install_id)
        )
        assert r.status_code == 401

    @pytest.mark.parametrize(
        "over",
        [
            {"version": "latest"},
            {"version": "1.2"},
            {"mode": "Single Mode!"},
            {"install_id": "xyz"},
            {"public_key": "short"},
        ],
    )
    def test_strict_schema(self, client, install, over):
        r = hb(client, install, **over)
        assert r.status_code in (401, 422)

    def test_unknown_fields_are_rejected(self, client, install):
        r = hb(client, install, hostname="mypc")
        assert r.status_code == 422 and err(r) == "VALIDATION_ERROR"
        assert r.json()["error"]["details"][0]["field"] == "hostname"

    def test_dev_versions_are_accepted(self, client, install):
        assert hb(client, install, version="0.9.0-dev").status_code == 204

    def test_not_json(self, client, install):
        raw = b"not json"
        r = client.post(
            "/v1/heartbeat", content=raw, headers=install.headers("POST", "/v1/heartbeat", raw)
        )
        assert r.status_code == 422


class TestRegister:
    def test_new_registration(self, client, app, install):
        r = reg(client, install)
        assert r.status_code == 201 and r.json() == {"status": "new"}
        [row] = rows(app, "SELECT * FROM registrations")
        assert row["install_id"] == install.install_id
        assert row["email"] == "priya@acme.dev" and row["site_url"] == "https://priya.dev"
        assert rows(app, "SELECT COUNT(*) AS n FROM installs")[0]["n"] == 1  # pinned by registering

    def test_email_domain_is_lowercased(self, client, app, install):
        reg(client, install, email="Priya@ACME.dev")
        assert rows(app, "SELECT email FROM registrations")[0]["email"] == "Priya@acme.dev"

    def test_reregister_updates_in_place(self, client, app, install):
        reg(client, install)
        r = reg(
            client, install, email="new@acme.dev", site_url="https://new.example", bot_name="Jane"
        )
        assert r.status_code == 200 and r.json() == {"status": "updated"}
        [row] = rows(app, "SELECT * FROM registrations")
        assert row["email"] == "new@acme.dev" and row["bot_name"] == "Jane"

    @pytest.mark.parametrize(
        "over",
        [
            {"email": "not-an-email"},
            {"email": "a@b"},
            {"email": "a b@c.dev"},
            {"site_url": "ftp://x.example"},
            {"site_url": "javascript:alert(1)"},
            {"site_url": "https://"},
            {"site_url": "https://a b.example"},
            {"site_url": "https://x.example/" + "a" * 300},
            {"bot_name": "x" * 81},
        ],
    )
    def test_validation(self, client, app, install, over):
        r = reg(client, install, **over)
        assert r.status_code == 422
        assert rows(app, "SELECT * FROM registrations") == []

    def test_register_requires_a_valid_signature(self, client, install):
        raw = json.dumps(install.register_body(), separators=(",", ":")).encode()
        r = client.post(
            "/v1/register", content=raw, headers=Install().headers("POST", "/v1/register", raw)
        )
        assert r.status_code == 401

    def test_cannot_register_under_someone_elses_install(self, client, app, install):
        reg(client, install)
        attacker = Install()
        raw = json.dumps(
            install.register_body(email="evil@x.dev", public_key=attacker.public_key),
            separators=(",", ":"),
        ).encode()
        r = client.post(
            "/v1/register",
            content=raw,
            headers=attacker.headers("POST", "/v1/register", raw, install_id=install.install_id),
        )
        assert r.status_code == 401
        assert rows(app, "SELECT email FROM registrations")[0]["email"] == "priya@acme.dev"

    def test_blocklist_by_email_and_domain(self, settings, clock):
        from fastapi.testclient import TestClient

        from app.main import create_app

        settings.blocklist = ("spam@x.dev", "bad.example")
        with TestClient(create_app(settings, clock)) as c:
            assert reg(c, Install(), email="spam@x.dev").status_code == 403
            assert reg(c, Install(), email="anyone@BAD.example").status_code == 403
            assert reg(c, Install(), email="ok@x.dev").status_code == 201


class TestUnregister:
    def test_delete_removes_the_registration_but_keeps_the_anonymous_install(
        self, client, app, install
    ):
        reg(client, install)
        r = install.delete(client, "/v1/register")
        assert r.status_code == 204
        assert rows(app, "SELECT * FROM registrations") == []
        assert len(rows(app, "SELECT * FROM installs")) == 1

    def test_delete_is_idempotent(self, client, install):
        hb(client, install)
        assert install.delete(client, "/v1/register").status_code == 204

    def test_attacker_cannot_delete_another_installs_registration(self, client, app, install):
        reg(client, install)
        attacker = Install()
        r = client.delete(
            "/v1/register",
            headers=attacker.headers("DELETE", "/v1/register", b"", install_id=install.install_id),
        )
        assert r.status_code == 401
        assert len(rows(app, "SELECT * FROM registrations")) == 1

    def test_unknown_install_cannot_delete(self, client):
        assert Install().delete(client, "/v1/register").status_code == 401

    def test_replayed_delete_is_rejected(self, client, install):
        reg(client, install)
        headers = install.headers("DELETE", "/v1/register", b"")
        assert client.delete("/v1/register", headers=headers).status_code == 204
        assert client.delete("/v1/register", headers=headers).status_code == 401

    def test_register_again_after_delete_is_new(self, client, install):
        reg(client, install)
        install.delete(client, "/v1/register")
        again = install.post(
            client, "/v1/register", install.register_body(), at=NOW + timedelta(seconds=1)
        )
        assert again.json() == {"status": "new"}


class TestLatest:
    def test_serves_releases_json(self, client):
        r = client.get("/v1/latest")
        assert r.status_code == 200
        body = r.json()
        assert body["latest"] == "0.10.1" and body["min_supported"] == "0.8.0"
        assert body["advisories"][0]["id"] == "MEBOT-2026-001"
        assert body["advisories"][0]["affected"] == "<0.10.1"

    def test_hot_reload(self, client, settings):
        assert client.get("/v1/latest").json()["latest"] == "0.10.1"
        settings.releases_path.write_text(
            json.dumps({**RELEASES, "latest": "0.11.0", "advisories": []})
        )
        body = client.get("/v1/latest").json()
        assert body["latest"] == "0.11.0" and body["advisories"] == []

    def test_broken_edit_keeps_serving_the_last_good_file(self, client, settings):
        client.get("/v1/latest")
        settings.releases_path.write_text("{ not json")
        assert client.get("/v1/latest").json()["latest"] == "0.10.1"
        settings.releases_path.write_text(json.dumps({"latest": "0.12.0"}))
        assert client.get("/v1/latest").json()["latest"] == "0.12.0"

    def test_edit_within_one_mtime_tick_is_still_seen(self, client, settings):
        import os

        client.get("/v1/latest")
        stamp = settings.releases_path.stat().st_mtime_ns
        settings.releases_path.write_text(json.dumps({"latest": "0.12.0"}))
        os.utime(settings.releases_path, ns=(stamp, stamp))  # coarse clocks: same mtime
        assert client.get("/v1/latest").json()["latest"] == "0.12.0"

    def test_missing_file_serves_a_placeholder(self, settings, clock):
        from fastapi.testclient import TestClient

        from app.main import create_app

        settings.releases_path = settings.releases_path.with_name("nope.json")
        with TestClient(create_app(settings, clock)) as c:
            assert c.get("/v1/latest").json()["latest"] == "0.0.0"


class TestStats:
    def test_requires_the_maintainer_token(self, client):
        assert client.get("/v1/stats").status_code == 401
        assert client.get("/v1/stats", headers={"Authorization": "Bearer nope"}).status_code == 401
        assert client.get("/v1/stats", headers={"Authorization": "admin-secret"}).status_code == 401

    def test_disabled_without_a_configured_token(self, settings, clock):
        from fastapi.testclient import TestClient

        from app.main import create_app

        settings.admin_token = ""
        with TestClient(create_app(settings, clock)) as c:
            assert c.get("/v1/stats", headers={"Authorization": "Bearer "}).status_code == 401

    def test_counts(self, client, clock):
        a, b, c = Install(), Install(), Install()
        hb(client, a)
        hb(client, b, version="0.8.0", mode="hosted")
        reg(client, c)
        clock.now = NOW + timedelta(days=10)
        a.post(client, "/v1/heartbeat", a.heartbeat_body(), at=clock.now)  # a stays active
        body = client.get("/v1/stats", headers={"Authorization": "Bearer admin-secret"}).json()
        assert body["active_7d"] == 1 and body["active_30d"] == 3
        assert body["by_version"] == {"0.9.0": 1} and body["by_mode"] == {"single": 1}
        assert body["registrations"] == 1 and body["total_installs"] == 3


def test_privacy_notice_is_served_as_text(client):
    r = client.get("/privacy")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    assert "registry: privacy" in r.text and "Not stored" in r.text


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_errors_use_the_standard_shape(client):
    r = client.get("/v1/stats")
    assert r.json() == {
        "error": {"code": "UNAUTHORIZED", "message": "Maintainer token required.", "status": 401}
    }
