import base64
import json
import os
import subprocess
from pathlib import Path

import pytest

from mebot import __version__
from mebot.config import Settings
from mebot.main import create_app
from mebot.telemetry import identity

VECTORS = json.loads((Path(__file__).parent / "registry_vectors.json").read_text("utf-8"))
REGISTRY_VECTORS = Path(__file__).resolve().parents[2] / "registry" / "tests" / "vectors.json"


def test_version_is_defined():
    assert __version__ == "0.9.0"


def test_first_boot_creates_the_key_and_it_persists(tmp_path):
    first = identity.load_or_create(tmp_path)
    assert (tmp_path / "install.key").exists()
    again = identity.load_or_create(tmp_path)
    assert again.install_id == first.install_id
    assert again.public_b64 == first.public_b64


def test_install_id_is_first_16_bytes_of_sha256_of_the_public_key(tmp_path):
    import hashlib

    key = identity.load_or_create(tmp_path)
    assert key.install_id == hashlib.sha256(key.public_raw).hexdigest()[:32]
    assert len(key.install_id) == 32 and key.id_prefix == key.install_id[:8]
    assert len(base64.b64decode(key.public_b64)) == 32


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_key_file_is_owner_only(tmp_path):
    identity.load_or_create(tmp_path)
    assert (tmp_path / "install.key").stat().st_mode & 0o777 == 0o600


def test_two_installs_get_different_identities(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = identity.load_or_create(tmp_path / "a")
    b = identity.load_or_create(tmp_path / "b")
    assert a.install_id != b.install_id


def test_deleting_the_file_creates_a_new_identity(tmp_path):
    old = identity.load_or_create(tmp_path)
    (tmp_path / "install.key").unlink()
    assert identity.load_or_create(tmp_path).install_id != old.install_id


@pytest.mark.parametrize("content", ["", "not base64!!", base64.b64encode(b"short").decode()])
def test_corrupt_key_file_is_left_alone_and_telemetry_idles(tmp_path, content):
    (tmp_path / "install.key").write_text(content)
    assert identity.load_or_create(tmp_path) is None
    assert (tmp_path / "install.key").read_text() == content


def test_unwritable_data_dir_returns_none(tmp_path):
    assert identity.load_or_create(tmp_path / "missing" / "dir") is None


def test_app_creates_the_key_on_first_boot(settings):
    app = create_app(settings)
    assert (settings.data_dir / "install.key").exists()
    assert app.state.install_key.install_id == identity.load_or_create(settings.data_dir).install_id


def test_key_is_never_committed():
    root = Path(__file__).resolve().parents[2]
    r = subprocess.run(
        ["git", "check-ignore", "backend/data/install.key", "install.key"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert r.stdout.split() == ["backend/data/install.key", "install.key"]


# --- signing: the same vectors the registry verifies --------------------------------------


def test_signing_matches_the_shared_vectors():
    key = identity.from_seed_hex(VECTORS["private_seed_hex"])
    assert key.public_b64 == VECTORS["public_key_b64"]
    assert key.install_id == VECTORS["install_id"]
    for case in VECTORS["cases"]:
        msg = identity.canonical(
            case["method"], case["path"], case["timestamp"], case["body"].encode()
        )
        assert msg.decode() == case["canonical"]
        assert key.sign(msg) == case["signature_b64"]


def test_signed_headers():
    key = identity.from_seed_hex(VECTORS["private_seed_hex"])
    case = VECTORS["cases"][0]
    h = identity.signed_headers(
        key, case["method"], case["path"], case["body"].encode(), int(case["timestamp"])
    )
    assert h == {
        "X-Mebot-Install": VECTORS["install_id"],
        "X-Mebot-Timestamp": case["timestamp"],
        "X-Mebot-Signature": case["signature_b64"],
    }


@pytest.mark.skipif(not REGISTRY_VECTORS.exists(), reason="registry/ not checked out")
def test_vectors_copy_is_in_sync_with_the_registry():
    assert json.loads(REGISTRY_VECTORS.read_text("utf-8")) == VECTORS


# --- config -------------------------------------------------------------------------------


def test_registry_settings_defaults(tmp_path, monkeypatch):
    for k in ("TELEMETRY", "REGISTRY_URL"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None, data_dir=tmp_path)
    assert s.telemetry == "on"
    assert s.registry_url == "https://registry.shivanshmishra.in"


def test_registry_url_is_normalised_and_validated(tmp_path, monkeypatch):
    monkeypatch.setenv("REGISTRY_URL", "http://localhost:8100/")
    assert Settings(_env_file=None, data_dir=tmp_path).registry_url == "http://localhost:8100"
    monkeypatch.setenv("REGISTRY_URL", "ftp://x.example")
    with pytest.raises(ValueError):
        Settings(_env_file=None, data_dir=tmp_path)


def test_telemetry_env_values(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEMETRY", "off")
    assert Settings(_env_file=None, data_dir=tmp_path).telemetry == "off"
    monkeypatch.setenv("TELEMETRY", "maybe")
    with pytest.raises(ValueError):
        Settings(_env_file=None, data_dir=tmp_path)
