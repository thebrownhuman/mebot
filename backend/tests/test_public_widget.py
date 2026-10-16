from tests.test_widget_frames import set_widget


def test_public_widget_defaults(admin_client):
    r = admin_client.get("/api/public/widget/shivansh")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "title": "Shivansh's assistant",
        "primary_color": "#0f766e",
        "theme": "auto",
        "position": "right",
        "avatar_url": None,
        "launcher_label": None,
        "greeting": body["greeting"],
        "suggested_questions": [],
        "show_orb": False,
        "auto_open_seconds": None,
        "max_message_chars": 1000,
        "turnstile_site_key": None,
        "owner_first_name": "Shivansh",
        "paused": False,
    }
    assert body["greeting"]


def test_public_widget_reflects_settings_and_hides_admin_fields(admin_client, app):
    set_widget(
        app,
        title="Ask Shiv",
        primary_color="#1d4ed8",
        suggested_questions=["What does he work on?"],
        allowed_origins=["https://shivansh.dev"],
        allow_any_origin=False,
        show_orb=True,
    )
    body = admin_client.get("/api/public/widget/shivansh").json()
    assert body["title"] == "Ask Shiv" and body["primary_color"] == "#1d4ed8"
    assert body["suggested_questions"] == ["What does he work on?"] and body["show_orb"]
    assert "allowed_origins" not in body and "allow_any_origin" not in body


def test_public_widget_unknown_or_disabled(admin_client, app):
    r = admin_client.get("/api/public/widget/nobody")
    assert r.status_code == 404 and r.json()["error"]["code"] == "WIDGET_UNAVAILABLE"
    set_widget(app, enabled=False)
    assert admin_client.get("/api/public/widget/shivansh").status_code == 404


LAUNCHER = "/api/public/widget/shivansh/launcher"


def test_launcher_cors_only_for_allowed_sites(admin_client, app):
    set_widget(app, allowed_origins=["https://shivansh.dev"], launcher_label="Ask me")
    r = admin_client.get(LAUNCHER, headers={"Origin": "https://shivansh.dev"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://shivansh.dev"
    assert "origin" in r.headers["vary"].lower()
    assert r.json() == {
        "title": "Shivansh's assistant",
        "primary_color": "#0f766e",
        "position": "right",
        "theme": "auto",
        "launcher_label": "Ask me",
        "auto_open_seconds": None,
    }
    r = admin_client.get(LAUNCHER, headers={"Origin": "https://evil.dev"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "WIDGET_NOT_ALLOWED"
    assert "access-control-allow-origin" not in r.headers


def test_launcher_same_origin_and_any(admin_client, app):
    assert admin_client.get(LAUNCHER, headers={"Origin": "http://testserver"}).status_code == 200
    assert admin_client.get(LAUNCHER).status_code == 200
    set_widget(app, allow_any_origin=True)
    r = admin_client.get(LAUNCHER, headers={"Origin": "https://anyone.dev"})
    assert r.headers["access-control-allow-origin"] == "*"


def test_launcher_unknown_or_disabled(admin_client, app):
    assert admin_client.get("/api/public/widget/x/launcher").status_code == 404
    set_widget(app, enabled=False)
    assert admin_client.get(LAUNCHER).status_code == 404


def test_public_config_has_suggested_questions(admin_client, app):
    assert admin_client.get("/api/public/config").json()["suggested_questions"] == []
    set_widget(app, suggested_questions=["Tech stack?"])
    assert admin_client.get("/api/public/config").json()["suggested_questions"] == ["Tech stack?"]
