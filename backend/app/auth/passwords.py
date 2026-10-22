"""Argon2id password hashing. Plain passwords are never stored or logged."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()
# Verified against when the username is unknown, so both failure paths cost the same.
_DUMMY_HASH = _hasher.hash("silobreaker-dummy-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """False for a missing hash, after spending the same work as a real check."""
    try:
        _hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return password_hash is not None
