"""/sdk/v1/mebot.js and /sdk/<version>/mebot.js; the old loader keeps working."""

import pytest

from mebot.main import create_app


@pytest.fixture
def sdk_client(settings, tmp_path):
    from fastapi.testclient import TestClient

    dist = tmp_path / "sdk"
    dist.mkdir()
    (dist / "mebot.js").write_text("/*sdk*/", encoding="utf-8")
    (dist / "VERSION").write_text("1.2.3\n", encoding="utf-8")
    widget = tmp_path / "dist" / "widget"
    widget.mkdir(parents=True)
    (widget / "v1.js").write_text("/*loader*/", encoding="utf-8")
    with TestClient(create_app(settings.model_copy(update={"sdk_dist": dist}))) as c:
        yield c


def test_latest_and_exact_version_caching(sdk_client):
    r = sdk_client.get("/sdk/v1/mebot.js")
    assert r.status_code == 200 and r.text == "/*sdk*/"
    assert r.headers["cache-control"] == "public, max-age=86400"
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.headers["access-control-allow-origin"] == "*"
    exact = sdk_client.get("/sdk/1.2.3/mebot.js")
    assert exact.status_code == 200 and "immutable" in exact.headers["cache-control"]
    for bad in ("1.2.4", "latest", "..%2F..", "v2"):
        assert sdk_client.get(f"/sdk/{bad}/mebot.js").status_code == 404


def test_one_line_loader_still_served(sdk_client):
    r = sdk_client.get("/widget/v1.js")
    assert r.status_code == 200 and r.text == "/*loader*/"


def test_not_built_is_404(settings, tmp_path):
    from fastapi.testclient import TestClient

    app = create_app(settings.model_copy(update={"sdk_dist": tmp_path / "missing"}))
    with TestClient(app) as c:
        assert c.get("/sdk/v1/mebot.js").status_code == 404
