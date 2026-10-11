import pytest

from mebot.config import ConfigError, Settings, resolve_secret_key


def test_defaults(tmp_path, monkeypatch):
    for k in ("MODE", "SECRET_KEY", "DATABASE_URL", "TELEMETRY", "CORS_ORIGINS"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None, data_dir=tmp_path)
    assert s.mode == "single"
    assert s.telemetry == "on"
    assert s.cors_origin_list == ["http://localhost:5173"]
    assert s.database_url.startswith("sqlite:///")
    assert s.database_url.endswith("data/mebot.db") or "mebot.db" in s.database_url


def test_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("MODE", "hosted")
    monkeypatch.setenv("SECRET_KEY", "abc")
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3")
    s = Settings(_env_file=None, data_dir=tmp_path)
    assert s.mode == "hosted"
    assert s.secret_key == "abc"
    assert s.cors_origin_list == ["http://a.test", "http://b.test"]
    assert s.ollama_model == "llama3"


def test_secret_generated_and_persisted_in_single_mode(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path, secret_key=None)
    k1 = resolve_secret_key(s)
    assert len(k1) >= 32
    assert (tmp_path / "secret.key").read_text().strip() == k1
    assert resolve_secret_key(Settings(_env_file=None, data_dir=tmp_path)) == k1


def test_hosted_requires_secret(tmp_path):
    s = Settings(_env_file=None, data_dir=tmp_path, mode="hosted", secret_key=None)
    with pytest.raises(ConfigError, match="SECRET_KEY"):
        resolve_secret_key(s)


def test_hosted_app_refuses_to_start(tmp_path):
    from mebot.main import create_app

    s = Settings(
        _env_file=None,
        data_dir=tmp_path,
        mode="hosted",
        secret_key=None,
        database_url=f"sqlite:///{(tmp_path / 'x.db').as_posix()}",
    )
    with pytest.raises(ConfigError):
        create_app(s)


def test_unwritable_data_dir_gives_clear_error(tmp_path):
    from mebot.main import create_app

    blocker = tmp_path / "file"
    blocker.write_text("x")  # a file where the data dir should be -> cannot mkdir
    s = Settings(
        _env_file=None,
        data_dir=blocker / "data",
        database_url=f"sqlite:///{(tmp_path / 'x.db').as_posix()}",
    )
    with pytest.raises(ConfigError, match="data directory"):
        create_app(s)
