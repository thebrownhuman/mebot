import pytest
from fastapi.testclient import TestClient

from mebot.config import Settings
from mebot.main import create_app

ADMIN_EMAIL = "owner@example.com"
ADMIN_PASSWORD = "correct horse battery"
LLM_KEY = "sk-test-SECRET-KEY-wxyz9876"
LLM = {"provider": "openai", "model": "gpt-4o-mini", "api_key": LLM_KEY}


class FakeLLM:
    """Stands in for every provider client (patched into mebot.llm.factory)."""

    def __init__(self):
        self.fail = None  # LLMError raised by test() and stream_chat()
        self.stream_fail = None  # LLMError raised by stream_chat() only
        self.fail_after = None  # raised by stream_chat() after yielding all chunks
        self.chunks = ["Hel", "lo ", "there"]
        self.models = ["gpt-4o-mini", "gpt-4o"]
        self.built: list[dict] = []
        self.tests: list[str] = []
        self.streams: list[dict] = []
        self.usage = None  # Usage reported after the stream (None = provider silent)

    def build(self, provider_id, *, api_key=None, base_url=None):
        self.built.append({"provider": provider_id, "api_key": api_key, "base_url": base_url})
        return _FakeClient(self)


class _FakeClient:
    def __init__(self, ctl: FakeLLM):
        self.ctl = ctl
        self.usage = None

    async def test(self, *, model):
        from mebot.llm.base import TestResult

        self.ctl.tests.append(model)
        if self.ctl.fail:
            raise self.ctl.fail
        return TestResult(ok=True, latency_ms=12)

    async def stream_chat(self, messages, *, model, temperature, max_tokens):
        self.ctl.streams.append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        err = self.ctl.fail or self.ctl.stream_fail
        if err:
            raise err
        for c in self.ctl.chunks:
            yield c
        self.usage = self.ctl.usage
        if self.ctl.fail_after:
            raise self.ctl.fail_after

    async def list_models(self):
        return list(self.ctl.models)


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    from mebot.llm import factory

    ctl = FakeLLM()
    monkeypatch.setattr(factory, "build_client", ctl.build)
    return ctl


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        mode="single",
        data_dir=tmp_path,
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        ollama_host="http://ollama.invalid",
        telegram_workers=False,
        frontend_dist=tmp_path / "dist",
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
        "llm": dict(LLM),
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
