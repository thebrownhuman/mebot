"""The install's identity: an Ed25519 key pair in ``data/install.key``.

``install_id`` is the first 16 bytes (hex) of SHA-256 of the public key, which is also how
the registry derives it. Every registry request is signed with this key. Deleting the file
creates a new identity on the next start (the old registration is orphaned and purged by
the registry after 180 days).
"""

import base64
import binascii
import contextlib
import hashlib
import logging
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

log = logging.getLogger("mebot.telemetry")

KEY_FILE = "install.key"
HEADER_INSTALL = "X-Mebot-Install"
HEADER_TIMESTAMP = "X-Mebot-Timestamp"
HEADER_SIGNATURE = "X-Mebot-Signature"


@dataclass(frozen=True)
class InstallKey:
    private: Ed25519PrivateKey
    public_raw: bytes

    @property
    def public_b64(self) -> str:
        return base64.b64encode(self.public_raw).decode()

    @property
    def install_id(self) -> str:
        return install_id_for(self.public_raw)

    @property
    def id_prefix(self) -> str:
        """First 8 characters: all the UI ever shows."""
        return self.install_id[:8]

    def sign(self, message: bytes) -> str:
        return base64.b64encode(self.private.sign(message)).decode()


def install_id_for(public_raw: bytes) -> str:
    return hashlib.sha256(public_raw).digest()[:16].hex()


def canonical(method: str, path: str, timestamp: str, body: bytes) -> bytes:
    """The signed string: ``METHOD \\n path \\n timestamp \\n sha256(body)``."""
    return f"{method.upper()}\n{path}\n{timestamp}\n{hashlib.sha256(body).hexdigest()}".encode()


def signed_headers(key: InstallKey, method: str, path: str, body: bytes, now_ts: int) -> dict:
    stamp = str(int(now_ts))
    return {
        HEADER_INSTALL: key.install_id,
        HEADER_TIMESTAMP: stamp,
        HEADER_SIGNATURE: key.sign(canonical(method, path, stamp, body)),
    }


def _from_seed(seed: bytes) -> InstallKey:
    private = Ed25519PrivateKey.from_private_bytes(seed)
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return InstallKey(private=private, public_raw=public)


def from_seed_hex(seed_hex: str) -> InstallKey:
    return _from_seed(bytes.fromhex(seed_hex))


def load_or_create(data_dir: Path) -> InstallKey | None:
    """Load ``install.key`` or create it (mode 0600) on first boot.

    An unreadable or corrupt file returns None: telemetry then stays idle for this run and
    the file is left alone rather than silently replaced by a new identity.
    """
    path = data_dir / KEY_FILE
    if path.exists():
        try:
            seed = base64.b64decode(path.read_text("ascii").strip(), validate=True)
            if len(seed) != 32:
                raise ValueError("wrong length")
            return _from_seed(seed)
        except (OSError, ValueError, binascii.Error):
            log.warning("%s is unreadable; telemetry is idle until it is fixed or removed", path)
            return None
    seed = os.urandom(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(base64.b64encode(seed).decode() + "\n")
        with contextlib.suppress(OSError):  # no-op on Windows
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except FileExistsError:  # another process won the race
        return load_or_create(data_dir)
    except OSError:
        log.warning("could not write %s; telemetry is idle", path)
        return None
    return _from_seed(seed)
