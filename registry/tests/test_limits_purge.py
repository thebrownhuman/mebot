import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import purge
from app.limits import DailyCounter, SlidingWindow
from app.main import create_app
from tests.conftest import rows
from tests.helpers import NOW, Install


def hb(client, inst=None, at=NOW, **kw):
    inst = inst or Install()
    return inst.post(client, "/v1/heartbeat", inst.heartbeat_body(), at=at, **kw)


class TestSlidingWindow:
    def test_blocks_after_the_limit_and_recovers(self):
        t = {"now": 0.0}
        w = SlidingWindow(2, 60, lambda: t["now"])
        assert w.hit("a") is None and w.hit("a") is None
        assert w.hit("a") == 60
        t["now"] = 30
        assert w.hit("a") == 30
        t["now"] = 61
        assert w.hit("a") is None

    def test_keys_are_independent(self):
        w = SlidingWindow(1, 60, lambda: 0.0)
        assert w.hit("a") is None and w.hit("b") is None and w.hit("a") is not None


class TestDailyCounter:
    def test_resets_each_day(self):
        from datetime import date

        c = DailyCounter(2)
        d1, d2 = date(2026, 10, 17), date(2026, 10, 18)
        c.add("ip", d1)
        c.add("ip", d1)
        assert not c.allow("ip", d1) and c.allow("other", d1)
        assert c.allow("ip", d2)


class TestRateLimits:
    @pytest.mark.parametrize(
        ("path", "limit"), [("/v1/heartbeat", 10), ("/v1/register", 5), ("/v1/delete", 5)]
    )
    def test_per_ip_limits(self, client, path, limit):
        statuses = []
        for _ in range(limit + 1):
            inst = Install()
            if path == "/v1/heartbeat":
                statuses.append(hb(client, inst))
            elif path == "/v1/register":
                statuses.append(inst.post(client, path, inst.register_body()))
            else:
                statuses.append(inst.delete(client, "/v1/register"))
        assert statuses[limit].status_code == 429
        assert statuses[limit].json()["error"]["code"] == "RATE_LIMITED"
        assert int(statuses[limit].headers["retry-after"]) >= 1
        assert all(r.status_code != 429 for r in statuses[:limit])

    def test_limits_are_per_endpoint(self, client):
        for _ in range(5):
            Install().delete(client, "/v1/register")
        assert Install().delete(client, "/v1/register").status_code == 429
        assert hb(client).status_code == 204

    def test_limits_are_per_ip_when_behind_a_proxy(self, settings, clock):
        settings.trust_proxy = True
        with TestClient(create_app(settings, clock)) as c:
            c.headers["x-forwarded-for"] = "198.51.100.1"
            for _ in range(10):
                assert hb(c).status_code == 204
            assert hb(c).status_code == 429
            c.headers["x-forwarded-for"] = "198.51.100.2"
            assert hb(c).status_code == 204

    def test_forwarded_header_ignored_unless_trusted(self, client):
        for i in range(10):
            client.headers["x-forwarded-for"] = f"10.0.0.{i}"
            hb(client)
        client.headers["x-forwarded-for"] = "10.9.9.9"
        assert hb(client).status_code == 429  # same real client no matter what it claims

    def test_rejected_signatures_still_count(self, client):
        bad = Install()
        for _ in range(10):
            bad.post(client, "/v1/heartbeat", bad.heartbeat_body(version="bad"))
        assert hb(client).status_code == 429


class TestNewInstallThrottle:
    def test_more_than_twenty_new_installs_per_ip_per_day_are_throttled(self, settings, clock):
        settings.heartbeat_limit = (1000, 3600)
        with TestClient(create_app(settings, clock)) as c:
            for _ in range(20):
                assert hb(c).status_code == 204
            r = hb(c)
            assert r.status_code == 429 and r.json()["error"]["code"] == "TOO_MANY_INSTALLS"

    def test_existing_installs_keep_working_while_throttled(self, settings, clock):
        settings.heartbeat_limit = (1000, 3600)
        with TestClient(create_app(settings, clock)) as c:
            known = Install()
            assert hb(c, known).status_code == 204
            for _ in range(19):
                hb(c)
            assert hb(c).status_code == 429
            assert hb(c, known, at=NOW + timedelta(seconds=5)).status_code == 204

    def test_resets_the_next_day(self, settings, clock):
        settings.heartbeat_limit = (1000, 3600)
        with TestClient(create_app(settings, clock)) as c:
            for _ in range(20):
                hb(c)
            assert hb(c).status_code == 429
            clock.now = NOW + timedelta(days=1)
            assert hb(c, at=clock.now).status_code == 204

    def test_registering_counts_as_a_new_install_too(self, settings, clock):
        settings.heartbeat_limit = (1000, 3600)
        settings.register_limit = (1000, 3600)
        with TestClient(create_app(settings, clock)) as c:
            for _ in range(20):
                i = Install()
                i.post(c, "/v1/register", i.register_body())
            i = Install()
            assert i.post(c, "/v1/register", i.register_body()).status_code == 429


class TestBodyLimit:
    def test_declared_oversize_body(self, client):
        inst = Install()
        raw = json.dumps(inst.heartbeat_body(version="0.9.0")).encode() + b" " * 5000
        r = client.post(
            "/v1/heartbeat", content=raw, headers=inst.headers("POST", "/v1/heartbeat", raw)
        )
        assert r.status_code == 413 and r.json()["error"]["code"] == "BODY_TOO_LARGE"

    def test_streamed_oversize_body(self, client):
        inst = Install()

        def chunks():
            for _ in range(10):
                yield b"x" * 1000

        r = client.post(
            "/v1/heartbeat", content=chunks(), headers=inst.headers("POST", "/v1/heartbeat", b"")
        )
        assert r.status_code == 413

    def test_a_body_just_under_the_cap_is_parsed(self, client):
        inst = Install()
        r = inst.post(client, "/v1/register", inst.register_body(bot_name="b" * 80))
        assert r.status_code == 201
        assert len(json.dumps(inst.register_body(bot_name="b" * 80))) < 4096


class TestPurge:
    def test_removes_installs_unseen_for_180_days_with_their_registrations(
        self, client, app, settings, clock
    ):
        old, fresh = Install(), Install()
        old.post(client, "/v1/register", old.register_body())
        fresh.post(client, "/v1/register", fresh.register_body(email="f@x.dev"))
        clock.now = later = NOW + timedelta(days=179)
        fresh.post(client, "/v1/heartbeat", fresh.heartbeat_body(), at=later)
        assert purge.run(app.state.db, settings, NOW + timedelta(days=181))["installs"] == 1
        assert [r["install_id"] for r in rows(app, "SELECT install_id FROM installs")] == [
            fresh.install_id
        ]
        assert [r["email"] for r in rows(app, "SELECT email FROM registrations")] == ["f@x.dev"]

    def test_keeps_installs_seen_within_the_window(self, client, app, settings):
        hb(client)
        counts = purge.run(app.state.db, settings, NOW + timedelta(days=179))
        assert counts["installs"] == 0 and len(rows(app, "SELECT * FROM installs")) == 1

    def test_clears_expired_nonces_and_old_notifications(self, client, app, settings):
        inst = Install()
        inst.post(client, "/v1/register", inst.register_body())
        assert rows(app, "SELECT COUNT(*) AS n FROM nonces")[0]["n"] == 1
        with app.state.db.tx() as c:
            c.execute("UPDATE notifications SET status = 'sent'")
        counts = purge.run(app.state.db, settings, NOW + timedelta(days=31))
        assert counts["nonces"] == 1 and counts["notifications"] == 1

    def test_pending_notifications_are_never_purged(self, client, app, settings):
        inst = Install()
        inst.post(client, "/v1/register", inst.register_body())
        purge.run(app.state.db, settings, NOW + timedelta(days=400))
        assert rows(app, "SELECT COUNT(*) AS n FROM notifications")[0]["n"] == 1
