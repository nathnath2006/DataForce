"""Workspace AI model (Settings -> AI model): provider, model and a sealed API key.

The key is sealed with `connectors.crypto`, never returned, never logged and never put in an error
message. `sanitize_error` masks it anyway in anything that comes back from a provider.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.connectors import crypto
from app.db.models import LlmCredential
from app.enrichment.errors import EnrichmentConfigError
from app.services.errors import InvalidInputError

PROVIDERS = ("gemini", "anthropic")
SUGGESTED_MODELS: dict[str, list[str]] = {
    "gemini": ["gemini-2.5-flash", "gemini-2.5-pro"],
    "anthropic": ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"],
}
NOT_CONFIGURED = "Set an AI model in Settings"
ERROR_MAX_CHARS = 300

_TOKEN_RES = (
    re.compile(r"sk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{8,}"),
    re.compile(r"(?i)(?:bearer|x-api-key|x-goog-api-key|api[_-]?key)[=:\s]+\S+"),
    re.compile(r"[A-Za-z0-9_\-]{32,}"),
)


def sanitize_error(message: str, *secrets: str | None) -> str:
    """Mask the keys (the given ones and anything shaped like a key), cap at 300 characters."""
    text = message
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    for pattern in _TOKEN_RES:
        text = pattern.sub("***", text)
    text = " ".join(text.split())
    return text[:ERROR_MAX_CHARS]


def get_credential(session: Session, ws_id: uuid.UUID) -> LlmCredential | None:
    return session.scalar(select(LlmCredential).where(LlmCredential.workspace_id == ws_id))


def validate_key(raw: str) -> str:
    key = raw.strip()
    if not (20 <= len(key) <= 300) or not key.isprintable() or any(c.isspace() for c in key):
        raise InvalidInputError("the API key must be 20 to 300 printable characters, no spaces")
    return key


def save_settings(
    session: Session,
    ws_id: uuid.UUID,
    *,
    provider: str,
    model: str,
    api_key: str | None,
    settings: Settings,
) -> LlmCredential:
    if provider not in PROVIDERS:
        raise InvalidInputError("provider must be gemini or anthropic")
    key = validate_key(api_key) if api_key and api_key.strip() else None
    cred = get_credential(session, ws_id)
    if cred is None:
        if key is None:
            raise InvalidInputError("an API key is required")
        cred = LlmCredential(
            workspace_id=ws_id,
            provider=provider,
            model=model,
            api_key_enc=crypto.seal(key, settings),
        )
        session.add(cred)
    else:
        if provider != cred.provider and key is None:
            raise InvalidInputError("changing the provider requires a new API key")
        changed = provider != cred.provider or model != cred.model or key is not None
        cred.provider = provider
        cred.model = model
        if key is not None:
            cred.api_key_enc = crypto.seal(key, settings)
        if changed:
            cred.last_test_at = cred.last_test_ok = cred.last_error = None
    session.flush()
    return cred


def delete_settings(session: Session, ws_id: uuid.UUID) -> None:
    cred = get_credential(session, ws_id)
    if cred is not None:
        session.delete(cred)
        session.flush()


def require_credential(session: Session, ws_id: uuid.UUID) -> LlmCredential:
    cred = get_credential(session, ws_id)
    if cred is None:
        raise EnrichmentConfigError(NOT_CONFIGURED)
    return cred


def open_key(cred: LlmCredential, settings: Settings) -> str:
    return crypto.unseal(cred.api_key_enc, settings)


def record_test(session: Session, cred: LlmCredential, ok: bool, error: str | None) -> None:
    cred.last_test_at = datetime.now(UTC)
    cred.last_test_ok = ok
    cred.last_error = None if ok else (error or "the test call failed")[:ERROR_MAX_CHARS]
    session.flush()
