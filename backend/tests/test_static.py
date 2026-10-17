import pytest
from fastapi.testclient import TestClient

from mebot import __version__
from mebot.main import create_app

INDEX = "<!doctype html><title>mebot</title>"


@pytest.fixture
def dist_client(settings):
    d = settings.frontend_dist
    (d / "assets").mkdir(parents=True)
    (d / "embed-app").mkdir()
    (d / "widget").mkdir()
    (d / "index.html").write_text(INDEX)
    (d / "assets" / "index-abc123.js").write_text("console.log(1)")
    (d / "embed-app" / "embed.js").write_text("console.log(2)")
    (d / "widget" / "v1.js").write_text("console.log(3)")
    (d / "favicon.svg").write_text("<svg/>")
    with TestClient(create_app(settings)) as c:
        yield c


def test_hashed_assets_are_immutable(dist_client):
    r = dist_client.get("/assets/index-abc123.js")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_embed_bundle_and_index_are_no_cache(dist_client):
    r = dist_client.get("/embed-app/embed.js")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
    r = dist_client.get("/")
    assert r.text == INDEX and r.headers["cache-control"] == "no-cache"


def test_loader_cached_one_day(dist_client):
    r = dist_client.get("/widget/v1.js")
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=86400"
    assert r.headers["access-control-allow-origin"] == "*"  # parity with the nginx setup


def test_app_pages_cannot_be_framed(dist_client):
    r = dist_client.get("/admin")
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors" in r.headers["content-security-policy"]


@pytest.mark.parametrize("path", ["/admin", "/admin/login", "/setup", "/admin/widget/x"])
def test_spa_fallback_serves_index(dist_client, path):
    r = dist_client.get(path)
    assert r.status_code == 200 and r.text == INDEX
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-cache"


def test_root_files_served(dist_client):
    r = dist_client.get("/favicon.svg")
    assert r.status_code == 200 and r.text == "<svg/>"


@pytest.mark.parametrize("path", ["/api/nope", "/api/admin/nope/deeper", "/assets/missing.js"])
def test_fallback_does_not_swallow_api_or_asset_404s(dist_client, path):
    r = dist_client.get(path)
    assert r.status_code == 404
    assert r.text != INDEX


def test_api_404_is_json(dist_client):
    r = dist_client.get("/api/nope")
    assert r.headers["content-type"].startswith("application/json")


def test_no_traversal(dist_client, settings):
    (settings.frontend_dist.parent / "secret.txt").write_text("s3cret")
    r = dist_client.get("/..%2Fsecret.txt")
    assert "s3cret" not in r.text


def test_no_dist_no_fallback(client):
    assert client.get("/admin").status_code == 404


def test_health_reports_version(client):
    assert client.get("/api/health").json()["version"] == __version__
