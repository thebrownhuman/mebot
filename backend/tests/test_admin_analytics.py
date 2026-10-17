from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from mebot.models import AccessLog, Bot
from tests.conftest import csrf
from tests.dash_helpers import bot_id, counts, seed_session

Q = [("user", "What is his tech stack?"), ("assistant", "Python.")]


def ago(days):
    return datetime.now(UTC) - timedelta(days=days)


def put(c, **body):
    return c.put("/api/admin/account", json=body, headers=csrf(c))


def test_overview_requires_login(client):
    assert client.get("/api/admin/analytics/overview").status_code in (401, 403, 503)


def test_overview_shape_and_default_range(admin_client, app):
    seed_session(app, ago(1), Q, origin="https://shivansh.dev")
    r = admin_client.get("/api/admin/analytics/overview")
    assert r.status_code == 200, r.text
    b = r.json()
    assert set(b) == {"range", "kpis", "series", "top_questions", "sources", "status"}
    assert b["range"]["key"] == "7d" and len(b["series"]) == 7
    assert b["kpis"]["chats"]["value"] == 1
    assert b["sources"] == [{"origin": "https://shivansh.dev", "chats": 1}]


def test_overview_ranges_and_validation(admin_client):
    assert len(admin_client.get("/api/admin/analytics/overview?range=30d").json()["series"]) == 30
    assert admin_client.get("/api/admin/analytics/overview?range=1y").status_code == 422


def test_overview_cached_then_invalidated_by_timezone(admin_client, app):
    first = admin_client.get("/api/admin/analytics/overview").json()
    seed_session(app, ago(0), Q)
    assert admin_client.get("/api/admin/analytics/overview").json() == first  # cached 60 s
    assert put(admin_client, timezone="Asia/Kolkata").status_code == 200
    fresh = admin_client.get("/api/admin/analytics/overview").json()
    assert fresh["range"]["timezone"] == "Asia/Kolkata" and fresh["kpis"]["chats"]["value"] == 1


def test_account_get_and_put(admin_client, app):
    assert admin_client.get("/api/admin/account").json() == {
        "timezone": "UTC",
        "retention_days": 180,
        "retention_choices": [30, 90, 180, 365],
    }
    r = put(admin_client, timezone="Europe/Berlin", retention_days=90)
    assert r.status_code == 200 and r.json()["timezone"] == "Europe/Berlin"
    assert r.json()["retention_days"] == 90
    assert put(admin_client, retention_days=None).json()["retention_days"] is None
    # an omitted field is left alone
    assert put(admin_client, timezone="UTC").json()["retention_days"] is None
    with app.state.session_factory() as db:
        assert db.scalar(select(Bot.retention_days)) is None
        ev = db.scalars(select(AccessLog.event).where(AccessLog.event == "account_updated")).all()
    assert len(ev) == 3


def test_account_validation(admin_client):
    assert put(admin_client, timezone="Mars/Olympus").status_code == 422
    assert put(admin_client, retention_days=45).status_code == 422
    assert put(admin_client, bogus=1).status_code == 422


def test_account_put_needs_csrf(admin_client):
    assert admin_client.put("/api/admin/account", json={"retention_days": 30}).status_code == 403


def test_shortening_window_does_not_delete_now_but_previews(admin_client, app):
    seed_session(app, ago(200), Q)
    seed_session(app, ago(100), Q)
    seed_session(app, ago(2), Q)
    assert admin_client.get("/api/admin/account?preview_days=30").json()["will_delete"] == 2
    assert admin_client.get("/api/admin/account?preview_days=365").json()["will_delete"] == 0
    assert "will_delete" not in admin_client.get("/api/admin/account").json()
    put(admin_client, retention_days=30)
    assert counts(app)["sessions"] == 3  # the next purge applies it


def test_delete_all_requires_exact_confirm(admin_client, app):
    seed_session(app, ago(5), Q, contact=True)
    seed_session(app, ago(1), Q)
    url = "/api/admin/account/delete-conversations"
    for bad in ("delete", "", "DELETE "):
        r = admin_client.post(url, json={"confirm": bad}, headers=csrf(admin_client))
        assert r.status_code == 422
    assert counts(app)["sessions"] == 2
    r = admin_client.post(url, json={"confirm": "DELETE"}, headers=csrf(admin_client))
    assert r.status_code == 200 and r.json() == {"deleted_sessions": 2}
    c = counts(app)
    assert c["sessions"] == c["messages"] == c["contacts"] == 0
    with app.state.session_factory() as db:
        assert db.scalar(select(AccessLog.event).where(AccessLog.event == "CONVERSATIONS_DELETED"))
    assert bot_id(app)
