from sqlalchemy import select

from mebot.models import AccessLog
from tests.conftest import csrf, do_setup
from tests.test_widget_frames import set_widget


def put(c, **body):
    return c.put("/api/admin/widget", json=body, headers=csrf(c))


def fields(r):
    return {d["field"] for d in r.json()["error"]["details"]}


def test_requires_admin(client):
    do_setup(client)
    client.cookies.delete("mebot_session")
    assert client.get("/api/admin/widget").status_code == 401
    assert client.get("/api/admin/widget/snippets").status_code == 401


def test_put_requires_csrf(admin_client):
    r = admin_client.put("/api/admin/widget", json={"theme": "dark"})
    assert r.status_code == 403


def test_get_defaults(admin_client):
    body = admin_client.get("/api/admin/widget").json()
    assert body["enabled"] is True and body["allowed_origins"] == []
    assert body["allow_any_origin"] is False and body["primary_color"] == "#0f766e"
    assert body["suggested_questions"] == [] and body["auto_open_seconds"] is None
    assert body["needs_origins"] is True and body["slug"] == "shivansh"


def test_put_normalises_and_saves(admin_client):
    r = put(
        admin_client,
        allowed_origins=["https://Shivansh.dev/", "https://*.shivansh.dev", "https://shivansh.dev"],
        primary_color="#1D4ED8",
        theme="dark",
        position="left",
        title="  Ask Shiv  ",
        launcher_label="Ask about me",
        suggested_questions=[" What does he work on? ", "Tech stack?"],
        show_orb=True,
        auto_open_seconds=10,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["allowed_origins"] == ["https://shivansh.dev", "https://*.shivansh.dev"]
    assert body["primary_color"] == "#1d4ed8" and body["title"] == "Ask Shiv"
    assert body["suggested_questions"] == ["What does he work on?", "Tech stack?"]
    assert body["needs_origins"] is False
    assert admin_client.get("/api/admin/widget").json() == body
    csp = admin_client.get("/embed/shivansh").headers["content-security-policy"]
    assert csp == "frame-ancestors 'self' https://shivansh.dev https://*.shivansh.dev"


def test_put_partial_keeps_other_fields(admin_client):
    put(admin_client, theme="dark")
    assert put(admin_client, position="left").json()["theme"] == "dark"


def test_put_validation(admin_client):
    cases = [
        ({"allowed_origins": ["http://shivansh.dev"]}, "allowed_origins.0"),
        ({"allowed_origins": [f"https://s{i}.dev" for i in range(21)]}, "allowed_origins"),
        ({"primary_color": "red"}, "primary_color"),
        ({"theme": "neon"}, "theme"),
        ({"position": "top"}, "position"),
        ({"suggested_questions": ["q"] * 7}, "suggested_questions"),
        ({"suggested_questions": ["x" * 81]}, "suggested_questions.0"),
        ({"suggested_questions": ["  "]}, "suggested_questions.0"),
        ({"auto_open_seconds": 3}, "auto_open_seconds"),
        ({"auto_open_seconds": 121}, "auto_open_seconds"),
        ({"avatar_url": "javascript:alert(1)"}, "avatar_url"),
        ({"title": "x" * 61}, "title"),
        ({"unknown": 1}, "unknown"),
    ]
    for body, field in cases:
        r = put(admin_client, **body)
        assert r.status_code == 422, body
        assert field in fields(r), (body, r.json())


def test_any_origin_needs_confirm(admin_client):
    r = put(admin_client, allow_any_origin=True)
    assert r.status_code == 422 and "confirm_any_origin" in fields(r)
    r = put(admin_client, allow_any_origin=True, confirm_any_origin=True)
    assert r.status_code == 200 and r.json()["allow_any_origin"] is True
    assert r.json()["needs_origins"] is False
    # already on: other edits don't need the confirm again
    assert put(admin_client, theme="light").status_code == 200
    with admin_client.app.state.session_factory() as db:
        events = db.scalars(select(AccessLog.event)).all()
    assert "WIDGET_ANY_ORIGIN_ON" in events


def test_auto_open_nullable(admin_client):
    put(admin_client, auto_open_seconds=30)
    assert put(admin_client, auto_open_seconds=None).json()["auto_open_seconds"] is None


def test_snippets_use_public_url(admin_client, app):
    app.state.settings.public_url = "https://bot.example.com/"
    s = admin_client.get("/api/admin/widget/snippets").json()
    assert s["script"] == (
        '<script src="https://bot.example.com/widget/v1.js" data-bot="shivansh" async></script>'
    )
    assert 'data-mode="inline"' in s["inline"] and 'data-target="#mebot-chat"' in s["inline"]
    assert '<div id="mebot-chat"></div>' in s["inline"]
    assert 'src="https://bot.example.com/embed/shivansh?mode=inline"' in s["iframe"]


def test_snippets_fall_back_to_request_base(admin_client, app):
    app.state.settings.public_url = None
    s = admin_client.get("/api/admin/widget/snippets").json()
    assert 'src="http://testserver/widget/v1.js"' in s["script"]


# --- test page -------------------------------------------------------------------------


def test_widget_test_page_admin_only(admin_client):
    r = admin_client.get("/widget-test?color=%23112233&position=left&open=1")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert '<script src="/widget/v1.js" data-bot="shivansh"' in r.text
    assert 'data-color="#112233"' in r.text and 'data-position="left"' in r.text
    assert 'data-open="true"' in r.text
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    assert r.headers["content-security-policy"] == "frame-ancestors 'self'"
    admin_client.cookies.delete("mebot_session")
    assert admin_client.get("/widget-test").status_code == 401


def test_widget_test_page_drops_bad_overrides(admin_client):
    r = admin_client.get('/widget-test?color="><script>&position=top&mode=inline')
    assert "<script>" not in r.text
    assert "data-color" not in r.text and "data-position" not in r.text
    assert 'data-mode="inline"' in r.text


# --- WIDGET_OPENED ---------------------------------------------------------------------


def opened(app):
    with app.state.session_factory() as db:
        return list(db.scalars(select(AccessLog).where(AccessLog.event == "WIDGET_OPENED")))


def test_widget_opened_logged_once_per_session_for_allowed_origin(admin_client, app):
    set_widget(app, allowed_origins=["https://*.shivansh.dev"])
    url = "/api/public/widget/shivansh/opened"
    body = {"session_id": "s-1", "origin": "https://www.shivansh.dev"}
    assert admin_client.post(url, json=body).status_code == 204
    assert admin_client.post(url, json=body).status_code == 204
    [row] = opened(app)
    assert row.detail == "https://www.shivansh.dev" and row.session_id == "s-1"


def test_widget_opened_rejects_unlisted_origin(admin_client, app):
    set_widget(app, allowed_origins=["https://shivansh.dev"])
    url = "/api/public/widget/shivansh/opened"
    for origin in ("https://evil.dev", "https://shivansh.dev/path", "nonsense"):
        r = admin_client.post(url, json={"session_id": "s", "origin": origin})
        assert r.status_code == 204
    assert opened(app) == []


def test_widget_opened_any_origin(admin_client, app):
    url = "/api/public/widget/shivansh/opened"
    admin_client.post(url, json={"session_id": "a", "origin": "https://anyone.dev"})
    assert opened(app) == []
    set_widget(app, allow_any_origin=True)
    admin_client.post(url, json={"session_id": "b", "origin": "https://anyone.dev"})
    assert [r.detail for r in opened(app)] == ["https://anyone.dev"]


def test_widget_opened_unknown_slug(admin_client):
    r = admin_client.post("/api/public/widget/nobody/opened", json={"origin": "https://a.dev"})
    assert r.status_code == 404
