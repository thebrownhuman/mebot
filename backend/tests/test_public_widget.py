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
