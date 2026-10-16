from mebot.repos import bots
from mebot.repos import widget as widget_repo


def set_widget(app, **values):
    with app.state.session_factory() as db:
        bot = bots.get_primary(db)
        row = widget_repo.get_or_create(db, bot.id)
        widget_repo.update(db, row, values)
        db.commit()


def csp(r) -> str:
    return r.headers.get("content-security-policy", "")


def test_api_routes_deny_framing(client):
    r = client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY"
    assert csp(r) == "frame-ancestors 'self'"


def test_error_responses_also_deny_framing(client):
    r = client.get("/api/nope")
    assert r.headers["x-frame-options"] == "DENY"


def test_embed_default_allows_only_self(admin_client):
    r = admin_client.get("/embed/shivansh")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "x-frame-options" not in r.headers
    assert csp(r) == "frame-ancestors 'self'"
    assert '<div id="root"></div>' in r.text
    assert "/embed-app/embed.js" in r.text


def test_embed_lists_allowed_origins(admin_client, app):
    set_widget(app, allowed_origins=["https://shivansh.dev", "https://*.shivansh.dev"])
    r = admin_client.get("/embed/shivansh?mode=floating")
    assert csp(r) == "frame-ancestors 'self' https://shivansh.dev https://*.shivansh.dev"


def test_embed_any_origin(admin_client, app):
    set_widget(app, allowed_origins=["https://shivansh.dev"], allow_any_origin=True)
    assert csp(admin_client.get("/embed/shivansh")) == "frame-ancestors *"


def test_embed_disabled_or_unknown_is_unavailable(admin_client, app):
    r = admin_client.get("/embed/someone-else")
    assert r.status_code == 404 and csp(r) == "frame-ancestors 'none'"
    assert "x-frame-options" not in r.headers
    assert "unavailable" in r.text.lower() and "/embed-app/" not in r.text
    set_widget(app, enabled=False)
    r = admin_client.get("/embed/shivansh")
    assert r.status_code == 404 and csp(r) == "frame-ancestors 'none'"


def test_embed_before_setup_is_unavailable(client):
    r = client.get("/embed/default")
    assert r.status_code == 404 and csp(r) == "frame-ancestors 'none'"


def test_embed_ignores_corrupt_stored_origins(admin_client, app):
    with app.state.session_factory() as db:
        row = widget_repo.get_or_create(db, bots.get_primary(db).id)
        row.allowed_origins = '["https://ok.dev", "https://x.dev; script-src *", 5]'
        db.commit()
    assert csp(admin_client.get("/embed/shivansh")) == "frame-ancestors 'self' https://ok.dev"


def test_loader_served_with_long_cache(client, settings):
    (settings.frontend_dist / "widget").mkdir(parents=True)
    (settings.frontend_dist / "widget" / "v1.js").write_text("/*loader*/")
    r = client.get("/widget/v1.js")
    assert r.status_code == 200 and r.text == "/*loader*/"
    assert "javascript" in r.headers["content-type"]
    assert r.headers["cache-control"] == "public, max-age=86400"
    r = client.get("/widget.js", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/widget/v1.js"


def test_loader_missing_build_is_404(client):
    assert client.get("/widget/v1.js").status_code == 404
