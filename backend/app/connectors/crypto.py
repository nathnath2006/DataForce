"""Fernet sealing of connector tokens and enriched contact values (DATAFORCE_SECRET_KEY).

Nothing here logs or echoes a plaintext, a ciphertext or the key.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings, get_settings
from app.enrichment.errors import EnrichmentConfigError, EnrichmentError

KEY_HINT = "DATAFORCE_SECRET_KEY is not set; run: dataforce secrets init"


class UnsealError(EnrichmentError):
    """A sealed value cannot be opened (the key was rotated or the data is corrupt)."""


def key_configured(settings: Settings | None = None) -> bool:
    key = (settings or get_settings()).dataforce_secret_key
    return key is not None and bool(key.get_secret_value().strip())


def _fernet(settings: Settings | None) -> Fernet:
    secret = (settings or get_settings()).dataforce_secret_key
    if secret is None or not secret.get_secret_value().strip():
        raise EnrichmentConfigError(KEY_HINT)
    try:
        return Fernet(secret.get_secret_value().strip().encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise EnrichmentConfigError(
            "DATAFORCE_SECRET_KEY is not a valid Fernet key; run: dataforce secrets init"
        ) from None


def seal(plain: str, settings: Settings | None = None) -> str:
    return _fernet(settings).encrypt(plain.encode("utf-8")).decode("ascii")


def unseal(sealed: str, settings: Settings | None = None) -> str:
    fernet = _fernet(settings)
    try:
        return fernet.decrypt(sealed.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError):
        raise UnsealError(
            "a stored secret cannot be decrypted with the current DATAFORCE_SECRET_KEY "
            "(was it changed?); reconnect"
        ) from None
