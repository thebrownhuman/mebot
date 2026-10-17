import shutil

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
        # If set, each stream_chat() call yields the next reply instead of `chunks`.
        self.replies: list[str] = []
        self.embed_fail = None  # LLMError raised by embed()
        self.embed_calls: list[dict] = []

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
        if self.ctl.replies:
            reply = self.ctl.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            yield reply
            return
        for c in self.ctl.chunks:
            yield c
        self.usage = self.ctl.usage
        if self.ctl.fail_after:
            raise self.ctl.fail_after

    async def list_models(self):
        return list(self.ctl.models)

    embed_tokens = None

    async def embed(self, texts, *, model):
        """Bag-of-words vectors (hashed into 64 dims): similar wording -> similar vector."""
        import zlib

        self.ctl.embed_calls.append({"texts": list(texts), "model": model})
        if self.ctl.embed_fail:
            raise self.ctl.embed_fail
        out = []
        for t in texts:
            v = [0.0] * 64
            for w in t.lower().split():
                v[zlib.crc32(w.encode()) % 64] += 1.0
            out.append(v)
        return out


@pytest.fixture(autouse=True)
def fake_llm(monkeypatch):
    from mebot.llm import factory

    ctl = FakeLLM()
    monkeypatch.setattr(factory, "build_client", ctl.build)
    return ctl


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Anything that falls back to Settings() (CLI, migrations) stays in this test's tmp dir,
    never backend/data, and xdist workers never share a data dir."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))


@pytest.fixture(autouse=True)
def clear_analytics_cache():
    from mebot.analytics import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture(scope="session")
def migrated_db(tmp_path_factory):
    """One DB migrated to head per test worker; each test gets a copy (migrating per test
    was ~2-3 s of setup each). create_app still runs upgrade, which is then a no-op."""
    from mebot.db import run_migrations

    path = tmp_path_factory.mktemp("template") / "template.db"
    run_migrations(f"sqlite:///{path.as_posix()}", secret_key="unused-no-rows")
    return path


@pytest.fixture(autouse=True)
def fast_password_hashing(monkeypatch):
    """Tests don't need production argon2 cost; hashes still embed their own params."""
    from argon2 import PasswordHasher

    from mebot.auth import passwords

    monkeypatch.setattr(
        passwords, "_hasher", PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    )


@pytest.fixture
def settings(tmp_path, migrated_db):
    shutil.copyfile(migrated_db, tmp_path / "test.db")
    return Settings(
        _env_file=None,
        mode="single",
        data_dir=tmp_path,
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        ollama_host="http://ollama.invalid",
        telegram_workers=False,
        telemetry_workers=False,
        frontend_dist=tmp_path / "dist",
        github_token=None,
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


# --- Hosted mode (MODE=hosted) -------------------------------------------------------

HOSTED_SECRET = "hosted-test-secret-key-0123456789"


@pytest.fixture
def hosted_settings(settings):
    return settings.model_copy(
        update={
            "mode": "hosted",
            "secret_key": HOSTED_SECRET,
            "signup_mode": "open",
            "turnstile_site_key": "1x00000000000000000000AA",
            "turnstile_secret_key": "1x0000000000000000000000000000000AA",
            "public_url": "https://mebot.example",
        }
    )


@pytest.fixture
def hosted_app(hosted_settings):
    return create_app(hosted_settings)


class Tenant:
    def __init__(self, client, bot_id, slug, public_key, email):
        self.client, self.bot_id, self.slug = client, bot_id, slug
        self.public_key, self.email = public_key, email


def make_tenant(app, slug: str, *, verified=True, setup_done=True, status="active") -> Tenant:
    """A tenant (bot + verified owner + LLM config) and a TestClient logged in as it."""
    from mebot.auth import passwords
    from mebot.llm import service as llm
    from mebot.models import utcnow
    from mebot.repos import admins, bots

    email = f"{slug}@example.com"
    with app.state.session_factory() as db:
        bot = bots.create(db, slug, slug.title())
        bot.status = status
        if setup_done:
            bot.setup_completed_at = utcnow()
        admin = admins.create(db, email, passwords.hash_password(ADMIN_PASSWORD), bot_id=bot.id)
        if verified:
            admin.email_verified_at = utcnow()
        cfg = llm.ResolvedLLM(
            provider="openai", model="gpt-4o-mini", base_url=None, api_key=LLM_KEY
        )
        llm.store(db, bot.id, cfg, app.state.secret_key)
        db.commit()
        ids = (bot.id, bot.public_key)
    c = TestClient(app)
    c.__enter__()
    r = c.post(
        "/api/auth/login", json={"email": email, "password": ADMIN_PASSWORD}, headers=csrf(c)
    )
    assert r.status_code == 204, r.text
    return Tenant(c, ids[0], slug, ids[1], email)


@pytest.fixture
def tenants(hosted_app):
    """Two live tenants, A and B, each with a logged-in client."""
    a, b = make_tenant(hosted_app, "alice"), make_tenant(hosted_app, "bobby")
    yield a, b
    for t in (a, b):
        t.client.__exit__(None, None, None)
