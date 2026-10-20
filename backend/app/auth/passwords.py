"""Password hashing (scrypt, stdlib only) and the password policy.

Format: `scrypt$<log2 N>$<r>$<p>$<b64 salt>$<b64 hash>`, so the cost can change later.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from app.services.errors import InvalidInputError

LOG_N = 15
R = 8
P = 1
SALT_BYTES = 16
KEY_BYTES = 32
MIN_LENGTH = 10
MAX_LENGTH = 200
_MAXMEM = 128 * 1024 * 1024


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _derive(password: str, salt: bytes, log_n: int, r: int, p: int, length: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**log_n, r=r, p=p, dklen=length, maxmem=_MAXMEM
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    key = _derive(password, salt, LOG_N, R, P, KEY_BYTES)
    return f"scrypt${LOG_N}${R}${P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check; False for any malformed hash."""
    try:
        scheme, log_n, r, p, salt_b64, key_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(key_b64)
        key = _derive(password, salt, int(log_n), int(r), int(p), len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(key, expected)


_DUMMY_HASH = hash_password("dataforce-dummy-password")


def dummy_verify(password: str) -> None:
    """Spend the same time as a real check, for an unknown or passwordless account."""
    verify_password(password, _DUMMY_HASH)


def validate_password(password: str) -> None:
    """Policy for a NON-empty password."""
    if len(password) < MIN_LENGTH:
        raise InvalidInputError(f"the password must have at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise InvalidInputError(f"the password must have at most {MAX_LENGTH} characters")


def hash_for_new_password(password: str, *, empty_allowed: bool) -> str | None:
    """The hash to store (None = empty password), or InvalidInputError when the policy refuses.
    `empty_allowed` comes from `empty_password_allowed`."""
    if password == "":
        if not empty_allowed:
            raise InvalidInputError(
                "an empty password is only allowed for demo workspaces on this computer; "
                f"use at least {MIN_LENGTH} characters"
            )
        return None
    validate_password(password)
    return hash_password(password)
