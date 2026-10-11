import pytest
from fastapi.testclient import TestClient

from mebot.config import Settings
from mebot.main import create_app


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
