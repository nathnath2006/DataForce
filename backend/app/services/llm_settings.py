"""Workspace AI model (Settings -> AI model): provider, model and a sealed API key.

The key is sealed with `connectors.crypto`, never returned, never logged and never put in an error
message. `sanitize_error` masks it anyway in anything that comes back from a provider.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.connectors import crypto
from app.db.models import LlmCredential, UserSession
from app.enrichment.errors import EnrichmentConfigError
from app.services.errors import InvalidInputError

PROVIDERS = ("gemini", "anthropic")
SUGGESTED_MODELS: dict[str, list[str]] = {
    "gemini": [
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-pro-preview",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
    ],
    "anthropic": ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"],
}
NOT_CONFIGURED = "Set an AI model in Settings"
NOT_CONFIGURED_DEMO = "Add your own key to try AI in the demo"
DEMO_INFO_KEY = "demo_session_id"  # set on the DB session by app.auth.demo.bind_session
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
    text = "".join(" " if unicodedata.category(ch) == "Cc" else ch for ch in text)
    text = " ".join(text.split())
    return text[:ERROR_MAX_CHARS]


def stored_credential(session: Session, ws_id: uuid.UUID) -> LlmCredential | None:
    """The workspace's own saved AI model (the settings page edits only this one)."""
    return session.scalar(select(LlmCredential).where(LlmCredential.workspace_id == ws_id))


def get_credential(session: Session, ws_id: uuid.UUID) -> LlmCredential | None:
    """The AI model to use for a call. THE one place every AI feature (assistant, summaries,
    titles, themes, organisation) loads it. In a demo session this is only the visitor's own key
    from their session, and never the workspace's stored key, even when the workspace has one."""
    if DEMO_INFO_KEY in session.info:
        row = session.get(UserSession, session.info[DEMO_INFO_KEY])
        if row is None or not (row.llm_provider and row.llm_model and row.llm_key_enc):
            return None
        # Not added to the session: it is never written. The key stays sealed until used.
        return LlmCredential(
            workspace_id=ws_id,
            provider=row.llm_provider,
            model=row.llm_model,
            api_key_enc=row.llm_key_enc,
            allow_meeting_org=True,  # synthetic data and the visitor's own key
        )
    return stored_credential(session, ws_id)


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
    cred = stored_credential(session, ws_id)
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
        if provider != cred.provider or model != cred.model:
            cred.allow_meeting_org = False  # consent was given for that provider and model
        cred.provider = provider
        cred.model = model
        if key is not None:
            cred.api_key_enc = crypto.seal(key, settings)
        if changed:
            cred.last_test_at = cred.last_test_ok = cred.last_error = None
    session.flush()
    return cred


def delete_settings(session: Session, ws_id: uuid.UUID) -> None:
    cred = stored_credential(session, ws_id)
    if cred is not None:
        session.delete(cred)
        session.flush()


def require_credential(session: Session, ws_id: uuid.UUID) -> LlmCredential:
    cred = get_credential(session, ws_id)
    if cred is None:
        raise EnrichmentConfigError(
            NOT_CONFIGURED_DEMO if DEMO_INFO_KEY in session.info else NOT_CONFIGURED
        )
    return cred


def open_key(cred: LlmCredential, settings: Settings) -> str:
    return crypto.unseal(cred.api_key_enc, settings)


def record_test(session: Session, cred: LlmCredential, ok: bool, error: str | None) -> None:
    cred.last_test_at = datetime.now(UTC)
    cred.last_test_ok = ok
    cred.last_error = None if ok else (error or "the test call failed")[:ERROR_MAX_CHARS]
    session.flush()


# --- The models a workspace's own key can use ---------------------------------------------------
log = logging.getLogger(__name__)

MODEL_CACHE_TTL_S = 3600.0
FAIL_CACHE_TTL_S = 60.0
MAX_GEMINI_PAGES = 5
_fail_cache: dict[tuple[uuid.UUID, str], float] = {}
DEFAULT_MODELS = {"gemini": "gemini-3.5-flash", "anthropic": "claude-haiku-5-5"}
# Gemini lists embedding, speech, image and live models too: only text generation is useful here.
_NOT_TEXT = ("embedding", "tts", "image", "live", "audio", "robotics", "computer-use", "aqa")
_models_lock = threading.Lock()
_models_cache: dict[tuple[uuid.UUID, str, str], tuple[float, list[str]]] = {}

ModelFetcher = Callable[[str, str, Settings], list[str]]


def _first_pages(pager):  # noqa: ANN001, ANN202
    """Items of at most MAX_GEMINI_PAGES pages of a google-genai pager."""
    for _ in range(MAX_GEMINI_PAGES):
        yield from list(pager.page)
        try:
            pager.next_page()
        except IndexError:
            return


def fetch_provider_models(provider: str, key: str, settings: Settings) -> list[str]:
    """Ask the provider which models this key can use (blocking; call from a sync route)."""
    timeout = settings.llm_timeout_s
    if provider == "gemini":
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=key,
            vertexai=False,
            http_options=types.HttpOptions(
                base_url="https://generativelanguage.googleapis.com/",
                timeout=int(timeout * 1000),
            ),
        )
        names = []
        pager = client.models.list()
        for m in _first_pages(pager):
            actions = m.supported_actions or []
            name = (m.name or "").removeprefix("models/")
            if "generateContent" in actions and name.startswith("gemini-"):
                if not any(bad in name for bad in _NOT_TEXT):
                    names.append(name)
        return names
    if provider == "anthropic":
        import anthropic

        client = anthropic.Anthropic(
            api_key=key, base_url="https://api.anthropic.com", timeout=timeout, max_retries=1
        )
        return [m.id for m in client.models.list(limit=100) if m.id.startswith("claude-")]
    raise InvalidInputError("provider must be gemini or anthropic")


def _fallback(provider: str) -> list[str]:
    return list(SUGGESTED_MODELS[provider])


def list_models(
    session: Session,
    ws_id: uuid.UUID,
    provider: str | None,
    settings: Settings,
    fetcher: ModelFetcher | None = None,
) -> tuple[str, str, list[str]]:
    """(provider, source, models) with source "provider" or "fallback". The provider call is
    made only with this workspace's own key for its own provider, and cached for an hour. Any
    failure, or no key, gives the static list; the key is never logged."""
    cred = get_credential(session, ws_id)
    name = provider or (cred.provider if cred else "gemini")
    if name not in PROVIDERS:
        raise InvalidInputError("provider must be gemini or anthropic")
    if cred is None or cred.provider != name:
        return name, "fallback", _fallback(name)
    cache_key = (ws_id, name, cred.api_key_enc[-16:])
    now = time.monotonic()
    with _models_lock:
        hit = _models_cache.get(cache_key)
    if hit is not None and now - hit[0] < MODEL_CACHE_TTL_S:
        return name, "provider", list(hit[1])
    with _models_lock:
        failed_at = _fail_cache.get((ws_id, name))
    if failed_at is not None and now - failed_at < FAIL_CACHE_TTL_S:
        return name, "fallback", _fallback(name)
    key = open_key(cred, settings)
    try:
        found = sorted(set((fetcher or fetch_provider_models)(name, key, settings)))
    except Exception as exc:  # any SDK, network or key problem: fall back, say why in the log
        log.warning("model list failed for %s: %s", name, sanitize_error(str(exc), key))
        with _models_lock:
            _fail_cache[(ws_id, name)] = now
        return name, "fallback", _fallback(name)
    if not found:
        return name, "fallback", _fallback(name)
    with _models_lock:
        _models_cache[cache_key] = (now, found)
    return name, "provider", list(found)


def clear_model_cache() -> None:
    with _models_lock:
        _models_cache.clear()
        _fail_cache.clear()
