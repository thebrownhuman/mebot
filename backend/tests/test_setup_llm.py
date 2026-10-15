import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from mebot.crypto import decrypt_secret
from mebot.llm.base import LLMError
from mebot.models import AccessLog, Admin, LLMConfig
from tests.conftest import LLM, LLM_KEY, csrf, do_setup, setup_body


def llm_test(client, **body):
    payload = {**LLM, **body}
    return client.post("/api/setup/llm-test", json=payload, headers=csrf(client))


def test_setup_requires_llm(client):
    body = setup_body()
    del body["llm"]
    r = client.post("/api/setup", json=body, headers=csrf(client))
    assert r.status_code == 422
    assert any(d["field"] == "llm" for d in r.json()["error"]["details"])


def test_setup_runs_test_and_stores_encrypted_key(client, app, fake_llm):
    assert do_setup(client).status_code == 201
    assert fake_llm.tests == ["gpt-4o-mini"]
    assert fake_llm.built[-1]["api_key"] == LLM_KEY
    with app.state.session_factory() as db:
        cfg = db.scalar(select(LLMConfig))
    assert cfg.provider == "openai" and cfg.model == "gpt-4o-mini"
    assert cfg.api_key_encrypted and LLM_KEY not in cfg.api_key_encrypted
    assert decrypt_secret(app.state.secret_key, cfg.api_key_encrypted) == LLM_KEY
    assert cfg.api_key_last4 == "9876" and cfg.last_test_ok is True


def test_setup_blocked_when_llm_test_fails(client, app, fake_llm):
    fake_llm.fail = LLMError("auth", "OpenAI rejected the API key (401)", 401)
    r = do_setup(client)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "LLM_TEST_FAILED"
    assert "rejected the API key" in err["message"]
    assert LLM_KEY not in r.text
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count(Admin.id))) == 0
        assert db.scalar(select(func.count(LLMConfig.id))) == 0
    assert client.get("/api/setup/status").json() == {"setup_required": True}


@pytest.mark.parametrize(
    "llm,field",
    [
        ({"provider": "nope", "model": "m", "api_key": "k"}, "llm.provider"),
        ({"provider": "openai", "model": "m"}, "llm.api_key"),
        ({"provider": "openai", "model": "m", "api_key": "  "}, "llm.api_key"),
        ({"provider": "openai", "model": "", "api_key": "k"}, "llm.model"),
        ({"provider": "openai_compatible", "model": "m"}, "llm.base_url"),
        ({"provider": "openai_compatible", "model": "m", "base_url": "ftp://x"}, "llm.base_url"),
    ],
)
def test_setup_llm_validation(client, fake_llm, llm, field):
    r = do_setup(client, llm=llm)
    assert r.status_code == 422
    assert any(d["field"] == field for d in r.json()["error"]["details"]), r.json()
    assert fake_llm.tests == []


def test_ollama_needs_no_key_and_defaults_base_url(client, app, fake_llm, settings):
    r = do_setup(client, llm={"provider": "ollama", "model": "gemma3"})
    assert r.status_code == 201
    assert fake_llm.built[-1] == {
        "provider": "ollama",
        "api_key": None,
        "base_url": settings.ollama_host,
    }
    with app.state.session_factory() as db:
        cfg = db.scalar(select(LLMConfig))
    assert cfg.api_key_encrypted is None and cfg.api_key_last4 is None


def test_custom_provider_without_key(client, fake_llm):
    r = do_setup(
        client,
        llm={"provider": "openai_compatible", "model": "m", "base_url": "http://llm.local/v1"},
    )
    assert r.status_code == 201
    assert fake_llm.built[-1]["base_url"] == "http://llm.local/v1"


# --- /api/setup/llm-test ---------------------------------------------------------


def test_llm_test_ok(client):
    r = llm_test(client)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "latency_ms": 12}


def test_llm_test_failure_scrubbed(client, fake_llm):
    fake_llm.fail = LLMError(
        "rate_limit", "OpenAI rate limited the request, try again shortly.", 429
    )
    r = llm_test(client)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "LLM_TEST_FAILED"
    assert "rate limited" in r.json()["error"]["message"]
    assert LLM_KEY not in r.text


def test_llm_test_requires_csrf(client):
    assert client.post("/api/setup/llm-test", json=LLM).status_code == 403


def test_llm_test_only_while_setup_required(admin_client):
    r = llm_test(admin_client)
    assert r.status_code == 409


def test_llm_test_rate_limited(client):
    for _ in range(10):
        assert llm_test(client).status_code == 200
    r = llm_test(client)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def test_llm_test_honours_setup_token(settings):
    from mebot.main import create_app

    settings.setup_token = "tok-123"
    with TestClient(create_app(settings)) as c:
        assert llm_test(c).status_code == 403
        assert llm_test(c, setup_token="tok-123").status_code == 200


def test_setup_llm_models(client, fake_llm):
    r = client.post("/api/setup/llm-models", json=LLM, headers=csrf(client))
    assert r.status_code == 200 and r.json() == {"models": ["gpt-4o-mini", "gpt-4o"]}


def test_setup_providers_public(client):
    r = client.get("/api/setup/llm-providers")
    providers = r.json()["providers"]
    gemini = next(p for p in providers if p["id"] == "gemini")
    assert gemini["key_required"] is True and gemini["key_url"].startswith("https://")
    assert "adapter" not in gemini


def test_key_never_logged(client, app, fake_llm, caplog):
    fake_llm.fail = LLMError("auth", "OpenAI rejected the API key (401)", 401)
    with caplog.at_level("DEBUG"):
        llm_test(client)
        do_setup(client)
        fake_llm.fail = None
        do_setup(client)
    assert LLM_KEY not in caplog.text
    with app.state.session_factory() as db:
        details = " ".join(str(r.detail) for r in db.scalars(select(AccessLog)))
    assert LLM_KEY not in details
