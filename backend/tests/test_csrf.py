from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from mebot.auth.csrf import CSRF_COOKIE, require_csrf
from mebot.config import Settings
from mebot.errors import install_error_handlers


def make(cors="http://localhost:5173"):
    app = FastAPI()
    install_error_handlers(app)
    app.state.settings = Settings(_env_file=None, cors_origins=cors)

    @app.post("/x", dependencies=[Depends(require_csrf)])
    def x():
        return {"ok": True}

    return TestClient(app)


def test_missing_token_403():
    c = make()
    r = c.post("/x")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "CSRF_FAILED"


def test_wrong_token_403():
    c = make()
    c.cookies.set(CSRF_COOKIE, "abc")
    assert c.post("/x", headers={"X-CSRF-Token": "abd"}).status_code == 403


def test_matching_token_ok():
    c = make()
    c.cookies.set(CSRF_COOKIE, "abc")
    assert c.post("/x", headers={"X-CSRF-Token": "abc"}).status_code == 200


def test_foreign_origin_rejected_even_with_token():
    c = make()
    c.cookies.set(CSRF_COOKIE, "abc")
    r = c.post("/x", headers={"X-CSRF-Token": "abc", "Origin": "https://evil.test"})
    assert r.status_code == 403


def test_same_host_and_cors_origin_allowed():
    c = make()
    c.cookies.set(CSRF_COOKIE, "abc")
    h = {"X-CSRF-Token": "abc"}
    assert c.post("/x", headers={**h, "Origin": "http://testserver"}).status_code == 200
    assert c.post("/x", headers={**h, "Origin": "http://localhost:5173"}).status_code == 200
    r = c.post("/x", headers={**h, "Referer": "http://localhost:5173/admin"})
    assert r.status_code == 200
    r = c.post("/x", headers={**h, "Referer": "https://evil.test/a"})
    assert r.status_code == 403
