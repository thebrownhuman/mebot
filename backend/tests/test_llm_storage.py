import sqlalchemy as sa

from mebot.crypto import decrypt_secret, encrypt_secret
from mebot.db import make_session_factory, run_migrations
from mebot.repos import llm_configs


def test_0004_llm_configs_table(tmp_path):
    url = f"sqlite:///{(tmp_path / 'l.db').as_posix()}"
    run_migrations(url)
    insp = sa.inspect(sa.create_engine(url))
    cols = {c["name"]: c for c in insp.get_columns("llm_configs")}
    assert set(cols) == {
        "id",
        "bot_id",
        "provider",
        "model",
        "base_url",
        "api_key_encrypted",
        "api_key_last4",
        "temperature",
        "max_tokens",
        "last_tested_at",
        "last_test_ok",
        "created_at",
        "updated_at",
    }
    for nullable in (
        "base_url",
        "api_key_encrypted",
        "api_key_last4",
        "last_tested_at",
        "last_test_ok",
    ):
        assert cols[nullable]["nullable"] is True
    assert any(
        ix["unique"] and ix["column_names"] == ["bot_id"] for ix in insp.get_indexes("llm_configs")
    )
    assert insp.get_foreign_keys("llm_configs") == []


def test_encrypt_roundtrip_and_not_plaintext():
    token = encrypt_secret("server-secret", "sk-abc-123456")
    assert "sk-abc-123456" not in token
    assert decrypt_secret("server-secret", token) == "sk-abc-123456"


def test_wrong_secret_key_returns_none():
    token = encrypt_secret("server-secret", "sk-abc-123456")
    assert decrypt_secret("another-secret", token) is None
    assert decrypt_secret("server-secret", "garbage") is None


def test_repo_save_and_overwrite(tmp_path):
    url = f"sqlite:///{(tmp_path / 'r.db').as_posix()}"
    run_migrations(url)
    with make_session_factory(url)() as db:
        assert llm_configs.get(db, "b1") is None
        cfg = llm_configs.save(
            db,
            "b1",
            provider="gemini",
            model="m1",
            base_url=None,
            api_key_encrypted="enc",
            api_key_last4="1234",
        )
        db.commit()
        assert cfg.temperature == 0.4 and cfg.max_tokens == 600
        assert cfg.last_test_ok is True and cfg.last_tested_at is not None
        again = llm_configs.save(
            db,
            "b1",
            provider="openai",
            model="m2",
            base_url=None,
            api_key_encrypted="enc2",
            api_key_last4="9999",
            temperature=0.9,
            max_tokens=100,
        )
        db.commit()
        assert again.id == cfg.id and again.provider == "openai" and again.max_tokens == 100
        llm_configs.record_test(db, again, ok=False)
        db.commit()
        assert llm_configs.get(db, "b1").last_test_ok is False
