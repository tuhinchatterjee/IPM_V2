"""Password hashing with Argon2id (argon2-cffi) — a memory-hard KDF stronger than
the werkzeug default. Hash on user creation/reset; verify at login."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_ph = PasswordHasher()


def hash_password(plaintext: str) -> str:
    return _ph.hash(plaintext)


def verify_password(stored_hash: str, plaintext: str) -> bool:
    try:
        return _ph.verify(stored_hash, plaintext)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True if the hash was made with weaker parameters than the current policy."""
    try:
        return _ph.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True
