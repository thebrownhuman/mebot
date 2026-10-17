import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.helpers import NOW, Install

RELEASES = {
    "latest": "0.10.1",
    "min_supported": "0.8.0",
    "released_at": "2026-10-10",
    "notes_url": "https://example.com/notes",
    "advisories": [
        {
            "id": "MEBOT-2026-001",
            "severity": "high",
            "affected": "<0.10.1",
            "title": "Session fixation",
            "url": "https://example.com/adv/1",
        }
    ],
}


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def settings(tmp_path):
    releases = tmp_path / "releases.json"
    releases.write_text(json.dumps(RELEASES))
    return Settings(
        data_dir=tmp_path / "data",
        releases_path=releases,
        admin_token="admin-secret",
        telegram_bot_token="123:TOKEN",
        telegram_chat_id="777",
        workers=False,
    )


@pytest.fixture
def app(settings, clock):
    return create_app(settings, clock)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def install():
    return Install()


def rows(app, sql: str, *args):
    with app.state.db.tx() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
