"""argon2id password hashing (argon2-cffi's default type is argon2id)."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 10
MAX_LENGTH = 256

_hasher = PasswordHasher()
# Verified against when the email is unknown, so both paths cost one argon2 verify.
_DUMMY_HASH = _hasher.hash("mebot-dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def dummy_verify(password: str) -> None:
    verify_password(_DUMMY_HASH, password)
