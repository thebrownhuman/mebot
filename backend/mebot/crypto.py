"""Symmetric encryption for stored secrets (LLM API keys, Telegram bot tokens).

Fernet key = HKDF-SHA256(SECRET_KEY, info=...): "mebot-llm-key" for LLM keys,
"mebot-telegram" for bot tokens, so one derived key can't read the other's values.
Changing SECRET_KEY makes stored values undecryptable; callers treat that as
"not configured".
"""

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_INFO = b"mebot-llm-key"
TELEGRAM_INFO = b"mebot-telegram"


def _fernet(secret_key: str, info: bytes) -> Fernet:
    raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(
        secret_key.encode()
    )
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_secret(secret_key: str, plaintext: str, info: bytes = _INFO) -> str:
    return _fernet(secret_key, info).encrypt(plaintext.encode()).decode()


def decrypt_secret(secret_key: str, token: str, info: bytes = _INFO) -> str | None:
    try:
        return _fernet(secret_key, info).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None
