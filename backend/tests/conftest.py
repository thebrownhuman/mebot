import pytest
from fastapi.testclient import TestClient

from mebot.config import Settings
from mebot.main import create_app

ADMIN_EMAIL = "owner@example.com"
ADMIN_PASSWORD = "correct horse battery"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        mode="single",
        data_dir=tmp_path,
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        ollama_host="http://ollama.invalid",
        ollama_model="me-bot",
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def csrf(client) -> dict[str, str]:
    """Headers for a mutating request: the double-submit token from the cookie."""
    if "mebot_csrf" not in client.cookies:
        client.get("/api/setup/status")
    return {"X-CSRF-Token": client.cookies["mebot_csrf"]}


def setup_body(**over) -> dict:
    body = {
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD,
        "bot_name": "Shivansh",
        "bot_slug": "shivansh",
        "registration_consent": False,
    }
    body.update(over)
    return body


def do_setup(client, **over):
    return client.post("/api/setup", json=setup_body(**over), headers=csrf(client))


@pytest.fixture
def admin_client(client):
    """A client that has completed setup and holds a logged-in admin session."""
    r = do_setup(client)
    assert r.status_code == 201, r.text
    return client
