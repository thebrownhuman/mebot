"""Symmetric encryption for stored secrets (LLM API keys).

Fernet key = HKDF-SHA256(SECRET_KEY, info="mebot-llm-key"). Changing SECRET_KEY makes
stored values undecryptable; callers treat that as "not configured".
"""

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_INFO = b"mebot-llm-key"


def _fernet(secret_key: str) -> Fernet:
    raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(
        secret_key.encode()
    )
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_secret(secret_key: str, plaintext: str) -> str:
    return _fernet(secret_key).encrypt(plaintext.encode()).decode()


def decrypt_secret(secret_key: str, token: str) -> str | None:
    try:
        return _fernet(secret_key).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None
