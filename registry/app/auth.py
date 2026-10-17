"""Signed-request verification with key pinning and replay protection."""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from app import signing
from app.db import Database, iso

_INSTALL_ID = re.compile(r"^[0-9a-f]{32}$")


class AuthError(Exception):
    def __init__(self, code: str, message: str, status: int = 401):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Verified:
    install_id: str
    public_key: str  # base64, as stored
    is_new: bool  # first contact: the key was not pinned before this request


def _header(headers: Mapping[str, str], name: str) -> str:
    value = headers.get(name)
    if not value:
        raise AuthError("SIGNATURE_MISSING", f"Missing {name} header.")
    return value


def verify_signed(
    *,
    headers: Mapping[str, str],
    method: str,
    path: str,
    body: bytes,
    db: Database,
    now: datetime,
    claimed_key: str | None = None,
) -> Verified:
    """Check the three ``X-Mebot-*`` headers against the pinned (or first-contact) key.

    ``claimed_key`` is the ``public_key`` from the request body, honoured only on first
    contact and required to match the pinned key afterwards. Raises ``AuthError``.
    """
    install_id = _header(headers, signing.HEADER_INSTALL).lower()
    stamp = _header(headers, signing.HEADER_TIMESTAMP)
    signature = _header(headers, signing.HEADER_SIGNATURE)
    if not _INSTALL_ID.match(install_id):
        raise AuthError("SIGNATURE_INVALID", "Malformed install id.")
    try:
        sent_at = int(stamp)
    except ValueError:
        raise AuthError("SIGNATURE_INVALID", "Malformed timestamp.") from None
    if abs(now.timestamp() - sent_at) > signing.MAX_SKEW_SECONDS:
        raise AuthError("TIMESTAMP_SKEW", "Request time is more than 5 minutes off.")

    with db.tx() as c:
        row = c.execute(
            "SELECT public_key FROM installs WHERE install_id = ?", (install_id,)
        ).fetchone()
    pinned = row["public_key"] if row else None
    if pinned is not None:
        if claimed_key is not None and claimed_key != pinned:
            raise AuthError("KEY_MISMATCH", "This install id is bound to a different key.")
        key_b64 = pinned
    elif claimed_key is not None:
        key_b64 = claimed_key
    else:
        raise AuthError("UNKNOWN_INSTALL", "Unknown install.")

    raw = signing.decode_public_key(key_b64)
    if raw is None:
        raise AuthError("SIGNATURE_INVALID", "Malformed public key.")
    if signing.install_id_for(raw) != install_id:
        raise AuthError("SIGNATURE_INVALID", "Install id does not match the public key.")

    sig_hash = hashlib.sha256(signature.encode()).hexdigest()
    with db.tx() as c:
        c.execute("DELETE FROM nonces WHERE expires_at < ?", (iso(now),))
        if c.execute("SELECT 1 FROM nonces WHERE sig_hash = ?", (sig_hash,)).fetchone():
            raise AuthError("REPLAYED", "This request was already seen.")
    if not signing.verify(raw, signature, signing.canonical(method, path, stamp, body)):
        raise AuthError("SIGNATURE_INVALID", "Signature does not verify.")
    with db.tx() as c:
        c.execute(
            "INSERT OR IGNORE INTO nonces (sig_hash, expires_at) VALUES (?, ?)",
            (sig_hash, iso(now + timedelta(seconds=signing.NONCE_TTL_SECONDS))),
        )
    return Verified(install_id=install_id, public_key=key_b64, is_new=pinned is None)
