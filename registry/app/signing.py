"""Request signing: Ed25519 over ``method \\n path \\n timestamp \\n sha256(body)``.

The same canonical string is built by mebot (see tests/vectors.json, shared by both apps).
``install_id`` is the first 16 bytes (hex) of SHA-256 of the raw public key.
"""

import base64
import binascii
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

HEADER_INSTALL = "X-Mebot-Install"
HEADER_TIMESTAMP = "X-Mebot-Timestamp"
HEADER_SIGNATURE = "X-Mebot-Signature"
MAX_SKEW_SECONDS = 300
NONCE_TTL_SECONDS = 600


def install_id_for(public_key_raw: bytes) -> str:
    return hashlib.sha256(public_key_raw).digest()[:16].hex()


def canonical(method: str, path: str, timestamp: str, body: bytes) -> bytes:
    digest = hashlib.sha256(body).hexdigest()
    return f"{method.upper()}\n{path}\n{timestamp}\n{digest}".encode()


def decode_public_key(b64: str) -> bytes | None:
    """Raw 32-byte Ed25519 key from standard base64, or None if malformed."""
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == 32 else None


def verify(public_key_raw: bytes, signature_b64: str, message: bytes) -> bool:
    try:
        sig = base64.b64decode(signature_b64, validate=True)
        Ed25519PublicKey.from_public_bytes(public_key_raw).verify(sig, message)
    except (binascii.Error, ValueError, InvalidSignature):
        return False
    return True
