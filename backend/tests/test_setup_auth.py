import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from mebot.models import Admin, AdminSession, Bot, utcnow
from mebot.repos import admin_sessions
from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, csrf, do_setup, setup_body

ADMIN_ROUTES = [
    ("GET", "/api/admin/profile/notes"),
    ("PUT", "/api/admin/profile/notes"),
    ("GET", "/api/admin/sessions"),
    ("GET", "/api/admin/sessions/abc/messages"),
    ("GET", "/api/admin/log"),
]


def call(client, method, path, **kw):
    if method == "PUT":
        kw.setdefault("json", {"content": "x"})
        kw.setdefault("headers", csrf(client))
    return client.request(method, path, **kw)


def login(client, email=ADMIN_EMAIL, password=ADMIN_PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# --- setup -------------------------------------------------------------------


def test_status_required_on_fresh_install(client):
    r = client.get("/api/setup/status")
    assert r.json() == {"setup_required": True}
    assert "mebot_csrf" in client.cookies


def test_setup_happy_path(client, app):
    r = do_setup(client, email="Owner@Example.com", registration_consent=True)
    assert r.status_code == 201
    assert r.json() == {"email": "owner@example.com", "bot_slug": "shivansh"}
    assert "mebot_session" in client.cookies
    assert client.get("/api/setup/status").json() == {"setup_required": False}
    assert client.get("/api/auth/me").json() == {
        "email": "owner@example.com",
        "bot_name": "Shivansh",
        "bot_slug": "shivansh",
    }
    with app.state.session_factory() as db:
        bot = db.scalar(select(Bot))
        assert bot.registration_consent is True and bot.setup_completed_at is not None


def test_consent_defaults_false(client, app):
    body = setup_body()
    del body["registration_consent"]
    assert client.post("/api/setup", json=body, headers=csrf(client)).status_code == 201
    with app.state.session_factory() as db:
        assert db.scalar(select(Bot)).registration_consent is False


def test_setup_twice_409(admin_client):
    r = do_setup(admin_client, email="other@example.com")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "SETUP_COMPLETED"


def test_setup_requires_csrf(client):
    assert client.post("/api/setup", json=setup_body()).status_code == 403


def test_concurrent_setup_one_wins(app):
    results = []
    barrier = threading.Barrier(4)

    def go(i):
        with TestClient(app) as c:
            h = csrf(c)
            barrier.wait()
            r = c.post("/api/setup", json=setup_body(email=f"u{i}@example.com"), headers=h)
            results.append(r.status_code)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [201, 409, 409, 409]
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count(Admin.id))) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("password", "short"),
        ("password", "x" * 257),
        ("email", "not-an-email"),
        ("bot_slug", "ab"),
        ("bot_slug", "Has Caps"),
        ("bot_slug", "admin"),
        ("bot_slug", "setup"),
        ("bot_slug", "api"),
        ("bot_slug", "widget"),
        ("bot_slug", "assets"),
        ("bot_name", "   "),
    ],
)
def test_setup_validation_422(client, field, value):
    r = do_setup(client, **{field: value})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert any(d["field"] == field for d in err["details"])


def test_setup_token_required_when_configured(settings):
    from mebot.main import create_app

    settings.setup_token = "s3cret-token"
    with TestClient(create_app(settings)) as c:
        assert do_setup(c).status_code == 403
        assert do_setup(c, setup_token="wrong").status_code == 403
        assert do_setup(c, setup_token="s3cret-token").status_code == 201


def test_existing_data_kept_after_setup(client, app):
    from mebot.profile.schemas import NotesIn
    from mebot.repos import bots, profile_items

    with app.state.session_factory() as db:
        bot = bots.get_or_create_default(db)
        profile_items.put_notes(db, bot.id, NotesIn(content="NAME: Kept"))
        db.commit()
    do_setup(client)
    assert client.get("/api/admin/profile/notes").json() == {"content": "NAME: Kept"}


# --- login / logout / me -----------------------------------------------------


def test_login_ok_and_me(admin_client):
    admin_client.cookies.clear()
    assert admin_client.get("/api/auth/me").status_code == 401
    r = login(admin_client, email="OWNER@example.com")
    assert r.status_code == 204
    assert "mebot_session" in admin_client.cookies and "mebot_csrf" in admin_client.cookies
    assert admin_client.get("/api/auth/me").json()["email"] == ADMIN_EMAIL


def test_login_wrong_password_and_unknown_email_same(admin_client):
    admin_client.cookies.clear()
    a = login(admin_client, password="wrong password!!")
    b = login(admin_client, email="nobody@example.com")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()
    assert a.json()["error"]["message"] == "Invalid email or password"


def test_login_rate_limited(admin_client):
    admin_client.cookies.clear()
    for _ in range(5):
        assert login(admin_client, password="wrong password!!").status_code == 401
    r = login(admin_client)  # correct password still blocked
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    assert r.json()["error"]["code"] == "RATE_LIMITED"


def test_logout(admin_client, app):
    r = admin_client.post("/api/auth/logout", headers=csrf(admin_client))
    assert r.status_code == 204
    assert "mebot_session" not in admin_client.cookies
    assert admin_client.get("/api/auth/me").status_code == 401
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count(AdminSession.id))) == 0


def test_logout_requires_csrf(admin_client):
    assert admin_client.post("/api/auth/logout").status_code == 403


def test_tampered_cookie_401_and_cleared(admin_client):
    admin_client.cookies.set("mebot_session", "tampered")
    r = admin_client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["error"] == {
        "code": "UNAUTHENTICATED",
        "message": "Login required",
        "status": 401,
    }
    assert "mebot_session=" in r.headers.get("set-cookie", "")


def test_expired_session_401(admin_client, app):
    with app.state.session_factory() as db:
        for s in db.scalars(select(AdminSession)):
            s.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert admin_client.get("/api/auth/me").status_code == 401


def test_session_cookie_flags(client):
    r = do_setup(client)
    cookies = r.headers.get_list("set-cookie")
    sess = next(c for c in cookies if c.startswith("mebot_session="))
    low = sess.lower()
    assert "httponly" in low and "samesite=lax" in low and "path=/" in low
    assert "secure" not in low  # plain http in tests
    tok = next(c for c in cookies if c.startswith("mebot_csrf="))
    assert "httponly" not in tok.lower()


def test_trust_proxy_forwarded_proto(settings):
    from mebot.main import create_app

    settings.trust_proxy = True
    with TestClient(create_app(settings)) as c:
        r = c.get("/api/setup/status", headers={"X-Forwarded-Proto": "https"})
        assert "secure" in r.headers["set-cookie"].lower()
    settings.trust_proxy = False
    with TestClient(create_app(settings)) as c:
        r = c.get("/api/setup/status", headers={"X-Forwarded-Proto": "https"})
        assert "secure" not in r.headers["set-cookie"].lower()


def test_cookie_secure_setting(settings):
    from mebot.main import create_app

    settings.cookie_secure = True
    app = create_app(settings)
    with TestClient(app, base_url="http://testserver") as c:
        r = c.get("/api/setup/status")
        assert "secure" in r.headers["set-cookie"].lower()
    with TestClient(app, base_url="https://testserver") as c:
        r = do_setup(c)
        sess = next(x for x in r.headers.get_list("set-cookie") if "mebot_session=" in x)
        assert "secure" in sess.lower()


def test_token_stored_hashed(admin_client, app):
    token = admin_client.cookies["mebot_session"]
    with app.state.session_factory() as db:
        ids = db.scalars(select(AdminSession.id)).all()
    assert ids == [admin_sessions.hash_token(token)]


# --- password change ---------------------------------------------------------


def test_password_change_revokes_other_sessions(admin_client, app):
    with TestClient(app) as other:
        assert login(other).status_code == 204
        r = admin_client.post(
            "/api/auth/password",
            json={"current_password": ADMIN_PASSWORD, "new_password": "brand new password"},
            headers=csrf(admin_client),
        )
        assert r.status_code == 204
        assert admin_client.get("/api/auth/me").status_code == 200
        assert other.get("/api/auth/me").status_code == 401
    admin_client.cookies.clear()
    assert login(admin_client).status_code == 401
    assert login(admin_client, password="brand new password").status_code == 204


def test_password_change_wrong_current_400(admin_client):
    r = admin_client.post(
        "/api/auth/password",
        json={"current_password": "not my password", "new_password": "brand new password"},
        headers=csrf(admin_client),
    )
    assert r.status_code == 400


def test_password_change_requires_auth(client):
    r = client.post(
        "/api/auth/password",
        json={"current_password": "x" * 10, "new_password": "y" * 10},
        headers=csrf(client),
    )
    assert r.status_code == 401


# --- route protection ----------------------------------------------------------


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_admin_routes_503_while_setup_required(client, method, path):
    r = call(client, method, path)
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "SETUP_REQUIRED"


def test_chat_503_while_setup_required(client):
    r = client.post("/api/chat", json={"session_id": "x", "message": "hi"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "SETUP_REQUIRED"


@pytest.mark.parametrize("method,path", ADMIN_ROUTES)
def test_admin_routes_401_without_cookie(admin_client, method, path):
    admin_client.cookies.pop("mebot_session")
    r = call(admin_client, method, path)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_admin_put_requires_csrf(admin_client):
    r = admin_client.put("/api/admin/profile/notes", json={"content": "x"})
    assert r.status_code == 403
    r = admin_client.put(
        "/api/admin/profile/notes", json={"content": "x"}, headers={"X-CSRF-Token": "wrong"}
    )
    assert r.status_code == 403


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/profile"),
        ("PUT", "/api/profile"),
        ("GET", "/api/sessions"),
        ("GET", "/api/session/abc/messages"),
        ("GET", "/api/log"),
    ],
)
def test_old_admin_paths_gone(admin_client, method, path):
    assert call(admin_client, method, path).status_code in (404, 405)


def test_public_routes_open_after_setup(admin_client):
    admin_client.cookies.clear()
    assert admin_client.get("/api/health").status_code == 200
    assert admin_client.post("/api/session", json={}).status_code == 200
    assert admin_client.get("/api/setup/status").status_code == 200
