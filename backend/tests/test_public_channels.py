from mebot.limits.memory import SlidingWindowLimiter
from tests.conftest import csrf


def add(c, **body):
    r = c.post("/api/admin/profile/links", json=body, headers=csrf(c))
    assert r.status_code == 201, r.text
    return r.json()


def test_returns_only_shared_with_hrefs(admin_client):
    add(admin_client, kind="email", value="Jane@Example.com")
    add(admin_client, kind="whatsapp", value="@jane_wa")
    add(admin_client, kind="instagram", value="@jane", label="My Insta")
    add(admin_client, kind="portfolio", value="https://jane.dev")
    add(admin_client, kind="phone", value="+91 98765 43210")  # not shared by default
    add(admin_client, kind="x", value="@hidden_x", share=False)
    r = admin_client.get("/api/public/contact-channels")
    assert r.status_code == 200
    assert r.json() == {
        "items": [
            {
                "kind": "email",
                "label": "Email",
                "display": "jane@example.com",
                "href": "mailto:jane@example.com",
            },
            {
                "kind": "whatsapp",
                "label": "WhatsApp",
                "display": "@jane_wa",
                "href": "https://wa.me/jane_wa",
            },
            {
                "kind": "instagram",
                "label": "My Insta",
                "display": "@jane",
                "href": "https://instagram.com/jane",
            },
            {
                "kind": "portfolio",
                "label": "Portfolio",
                "display": "jane.dev",
                "href": "https://jane.dev",
            },
        ]
    }
    assert "98765" not in r.text and "hidden_x" not in r.text


def test_empty_when_nothing_shared(admin_client):
    add(admin_client, kind="phone", value="+91 98765 43210")
    assert admin_client.get("/api/public/contact-channels").json() == {"items": []}


def test_share_off_removes_immediately(admin_client):
    cid = add(admin_client, kind="email", value="j@x.com")["id"]
    assert len(admin_client.get("/api/public/contact-channels").json()["items"]) == 1
    admin_client.put(
        f"/api/admin/profile/links/{cid}", json={"share": False}, headers=csrf(admin_client)
    )
    assert admin_client.get("/api/public/contact-channels").json() == {"items": []}


def test_rate_limited(admin_client, app):
    app.state.channels_limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
    for _ in range(2):
        assert admin_client.get("/api/public/contact-channels").status_code == 200
    r = admin_client.get("/api/public/contact-channels")
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"
    assert "Retry-After" in r.headers


def test_preview_warns_about_phone_in_notes_and_faq(admin_client):
    c = admin_client
    assert c.get("/api/admin/profile/preview").json()["warnings"] == []
    c.put(
        "/api/admin/profile/notes",
        json={"content": "Reach me on +91 98765 43210"},
        headers=csrf(c),
    )
    c.post(
        "/api/admin/profile/faqs",
        json={"question": "Phone?", "answer": "It is 555-123-4567"},
        headers=csrf(c),
    )
    warnings = c.get("/api/admin/profile/preview").json()["warnings"]
    assert any("notes" in w and "phone number" in w for w in warnings)
    assert any("FAQ" in w for w in warnings)


def test_preview_no_warning_for_shared_phone(admin_client):
    c = admin_client
    pid = add(c, kind="phone", value="+91 98765 43210")["id"]
    c.put(
        f"/api/admin/profile/links/{pid}",
        json={"share": True, "confirm_share_phone": True},
        headers=csrf(c),
    )
    c.put("/api/admin/profile/notes", json={"content": "+91 98765 43210"}, headers=csrf(c))
    assert c.get("/api/admin/profile/preview").json()["warnings"] == []
