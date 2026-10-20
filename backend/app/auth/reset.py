"""Stateless password-reset tokens (no table).

token = base64url(user_id | expiry | HMAC-SHA256(key, user_id | expiry | password_hash | disabled)).
Changing the password (or disabling the account) changes the MAC input, so a token is single-use.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid

from app.config import Settings
from app.db.models import UserAccount

VALID_FOR_S = 15 * 60
_LABEL = b"dataforce-password-reset-v1"


def _key(settings: Settings) -> bytes | None:
    secret = settings.dataforce_secret_key
    raw = secret.get_secret_value().strip() if secret is not None else ""
    return hashlib.sha256(_LABEL + raw.encode("utf-8")).digest() if raw else None


def _mac(key: bytes, user: UserAccount, expiry: int) -> str:
    msg = f"{user.id}|{expiry}|{user.password_hash or ''}|{int(user.disabled)}"
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).hexdigest()


def make_token(settings: Settings, user: UserAccount, *, now: float | None = None) -> str | None:
    key = _key(settings)
    if key is None:
        return None
    expiry = int((time.time() if now is None else now) + VALID_FOR_S)
    raw = f"{user.id}|{expiry}|{_mac(key, user, expiry)}"
    return base64.urlsafe_b64encode(raw.encode("ascii")).decode("ascii").rstrip("=")


def parse_token(token: str) -> tuple[uuid.UUID, int, str] | None:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("ascii")
        uid, expiry, mac = raw.split("|")
        return uuid.UUID(uid), int(expiry), mac
    except (ValueError, TypeError):
        return None


def verify(
    settings: Settings, user: UserAccount, expiry: int, mac: str, *, now: float | None = None
) -> bool:
    key = _key(settings)
    if key is None or user.disabled:
        return False
    good = hmac.compare_digest(_mac(key, user, expiry).encode(), mac.encode("ascii", "ignore"))
    return good and (time.time() if now is None else now) < expiry
