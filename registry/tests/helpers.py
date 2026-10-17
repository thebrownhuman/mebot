"""Test client that signs requests like a mebot install does."""

import base64
import json
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app import signing

VECTORS = json.loads((Path(__file__).parent / "vectors.json").read_text("utf-8"))
NOW = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)


class Install:
    """A fake mebot install: a keypair plus a signer."""

    def __init__(self, seed: bytes | None = None):
        self.key = (
            Ed25519PrivateKey.from_private_bytes(seed) if seed else Ed25519PrivateKey.generate()
        )
        self.raw = self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self.public_key = base64.b64encode(self.raw).decode()
        self.install_id = signing.install_id_for(self.raw)

    def headers(
        self,
        method: str,
        path: str,
        body: bytes = b"",
        *,
        at: datetime = NOW,
        install_id: str | None = None,
    ) -> dict[str, str]:
        stamp = str(int(at.timestamp()))
        sig = self.key.sign(signing.canonical(method, path, stamp, body))
        return {
            signing.HEADER_INSTALL: install_id or self.install_id,
            signing.HEADER_TIMESTAMP: stamp,
            signing.HEADER_SIGNATURE: base64.b64encode(sig).decode(),
            "Content-Type": "application/json",
        }

    def heartbeat_body(self, **over) -> dict:
        return {
            "install_id": self.install_id,
            "public_key": self.public_key,
            "version": "0.9.0",
            "mode": "single",
            **over,
        }

    def register_body(self, **over) -> dict:
        return {
            "install_id": self.install_id,
            "public_key": self.public_key,
            "version": "0.9.0",
            "email": "priya@acme.dev",
            "site_url": "https://priya.dev",
            **over,
        }

    def post(self, client, path: str, body: dict, *, at: datetime = NOW, **kw):
        raw = json.dumps(body, separators=(",", ":")).encode()
        return client.post(path, content=raw, headers=self.headers("POST", path, raw, at=at), **kw)

    def delete(self, client, path: str, *, at: datetime = NOW):
        return client.delete(path, headers=self.headers("DELETE", path, b"", at=at))
