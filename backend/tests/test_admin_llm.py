import pytest
from sqlalchemy import select

from mebot.crypto import decrypt_secret
from mebot.llm.base import LLMError
from mebot.models import LLMConfig
from tests.conftest import LLM_KEY, csrf

NEW_KEY = "sk-new-OTHER-KEY-5555"


def put(client, **body):
    return client.put("/api/admin/llm", json=body, headers=csrf(client))


def saved(app) -> LLMConfig:
    with app.state.session_factory() as db:
        return db.scalar(select(LLMConfig))


def test_get_never_returns_key(admin_client):
    r = admin_client.get("/api/admin/llm")
    assert r.status_code == 200
    body = r.json()
    assert LLM_KEY not in r.text and "api_key" not in body
    assert body["provider"] == "openai" and body["model"] == "gpt-4o-mini"
    assert body["has_key"] is True and body["api_key_last4"] == "9876"
    assert body["configured"] is True and body["status"] == "ok"
    assert body["last_test_ok"] is True and body["last_tested_at"]
    assert body["temperature"] == 0.4 and body["max_tokens"] == 600


def test_put_without_key_keeps_existing(admin_client, app, fake_llm):
    r = put(admin_client, provider="openai", model="gpt-4o", temperature=0.9, max_tokens=300)
    assert r.status_code == 200, r.text
    assert r.json()["model"] == "gpt-4o" and LLM_KEY not in r.text
    assert fake_llm.built[-1]["api_key"] == LLM_KEY  # tested with the saved key
    cfg = saved(app)
    assert decrypt_secret(app.state.secret_key, cfg.api_key_encrypted) == LLM_KEY
    assert cfg.temperature == 0.9 and cfg.max_tokens == 300


def test_put_with_new_key(admin_client, app):
    r = put(admin_client, provider="gemini", model="gemini-2.5-flash", api_key=NEW_KEY)
    assert r.status_code == 200
    cfg = saved(app)
    assert cfg.provider == "gemini" and cfg.api_key_last4 == "5555"
    assert decrypt_secret(app.state.secret_key, cfg.api_key_encrypted) == NEW_KEY


def test_switch_provider_without_key_422(admin_client, app, fake_llm):
    r = put(admin_client, provider="gemini", model="gemini-2.5-flash")
    assert r.status_code == 422
    assert any(d["field"] == "api_key" for d in r.json()["error"]["details"])
    assert saved(app).provider == "openai"
    assert len(fake_llm.tests) == 1  # only the setup test ran


def test_put_failed_test_keeps_old_config(admin_client, app, fake_llm):
    fake_llm.fail = LLMError("model", "OpenAI could not find that model (404)", 404)
    r = put(admin_client, provider="openai", model="gpt-nope")
    assert r.status_code == 422 and r.json()["error"]["code"] == "LLM_TEST_FAILED"
    cfg = saved(app)
    assert cfg.model == "gpt-4o-mini" and cfg.last_test_ok is True


@pytest.mark.parametrize("body", [{"temperature": 3}, {"max_tokens": 0}, {"max_tokens": 99999}])
def test_put_bounds(admin_client, body):
    assert put(admin_client, provider="openai", model="m", **body).status_code == 422


def test_test_saved_config_records_result(admin_client, app, fake_llm):
    r = admin_client.post("/api/admin/llm/test", headers=csrf(admin_client))
    assert r.status_code == 200 and r.json() == {"ok": True, "latency_ms": 12}
    fake_llm.fail = LLMError("auth", "OpenAI rejected the API key (401)", 401)
    r = admin_client.post("/api/admin/llm/test", headers=csrf(admin_client))
    assert r.status_code == 422 and LLM_KEY not in r.text
    assert saved(app).last_test_ok is False
    assert admin_client.get("/api/admin/llm").json()["last_test_ok"] is False


def test_test_submitted_config_does_not_save(admin_client, app, fake_llm):
    r = admin_client.post(
        "/api/admin/llm/test",
        json={"provider": "groq", "model": "llama", "api_key": NEW_KEY},
        headers=csrf(admin_client),
    )
    assert r.status_code == 200
    assert fake_llm.built[-1]["api_key"] == NEW_KEY
    assert saved(app).provider == "openai"


def test_models_uses_saved_key(admin_client, fake_llm):
    r = admin_client.get("/api/admin/llm/models", params={"provider": "openai"})
    assert r.status_code == 200 and r.json() == {"models": ["gpt-4o-mini", "gpt-4o"]}
    assert fake_llm.built[-1]["api_key"] == LLM_KEY
    admin_client.get("/api/admin/llm/models", params={"provider": "groq"})
    assert fake_llm.built[-1]["api_key"] is None  # other provider: saved key not sent


def test_models_with_submitted_key(admin_client, fake_llm):
    r = admin_client.post(
        "/api/admin/llm/models",
        json={"provider": "groq", "model": "x", "api_key": NEW_KEY},
        headers=csrf(admin_client),
    )
    assert r.status_code == 200
    assert fake_llm.built[-1]["api_key"] == NEW_KEY


def test_providers_list(admin_client):
    ids = [p["id"] for p in admin_client.get("/api/admin/llm/providers").json()["providers"]]
    assert "anthropic" in ids and "openai_compatible" in ids


def test_admin_llm_requires_auth(admin_client):
    admin_client.cookies.pop("mebot_session")
    assert admin_client.get("/api/admin/llm").status_code == 401
    assert put(admin_client, provider="openai", model="m").status_code == 401


def test_changed_secret_key_means_not_configured(admin_client, app):
    app.state.secret_key = "rotated-secret"
    body = admin_client.get("/api/admin/llm").json()
    assert body["configured"] is False and body["status"] == "undecryptable"
    assert body["has_key"] is False
    # Same provider, no key: nothing usable to keep -> must re-enter.
    r = put(admin_client, provider="openai", model="gpt-4o-mini")
    assert r.status_code == 422
    assert (
        put(admin_client, provider="openai", model="gpt-4o-mini", api_key=NEW_KEY).status_code
        == 200
    )
    assert admin_client.get("/api/admin/llm").json()["status"] == "ok"


def test_not_configured_view(admin_client, app):
    with app.state.session_factory() as db:
        db.query(LLMConfig).delete()
        db.commit()
    body = admin_client.get("/api/admin/llm").json()
    assert body["configured"] is False and body["status"] == "missing"
    assert body["provider"] is None and body["has_key"] is False
