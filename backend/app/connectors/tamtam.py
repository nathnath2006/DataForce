"""TamTam connector orchestration: connect, callback, token refresh, check, disconnect, status.

Rules (docs/UI-CONTRACT.md sections 2, 4, 5):
* DB access is sync and short (run in the thread pool); network access is async. No database
  transaction is held open across a network call: each phase commits or rolls back first.
* Tokens, the client secret and the PKCE verifier exist in clear only inside these functions.
  They are never logged, never put in a message and never returned to the browser.
* A token only ever goes to the resource it was issued for.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import re
import secrets
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.schemas import ConnectorOut, PricingOut, ToolOut
from app.config import Settings
from app.connectors import oauth, store
from app.connectors.crypto import UnsealError, key_configured, seal, unseal
from app.db.models import ConnectorCredential, Workspace
from app.enrichment.errors import EnrichmentConfigError, EnrichmentError
from app.enrichment.tamtam_mcp import (
    DEFAULT_CREDIT_COSTS,
    DEFAULT_TOOL_MAP,
    MAX_TOOLS,
    TamTamMCPEnrichment,
    _tool_info,
    open_http_session,
    safe_server_text,
)

log = logging.getLogger(__name__)

TOOL_DESCRIPTION_CHARS = 500
CHECK_TIMEOUT_S = 30.0
MAX_CODE_CHARS = 2048
MAX_STATE_CHARS = 256

# Fixed reasons of the callback redirect (the only values that ever reach the URL).
DENIED = "denied"
EXPIRED = "expired"
INVALID_STATE = "invalid_state"
EXCHANGE_FAILED = "exchange_failed"
SERVER_ERROR = "server_error"


class ConnectorNotUsable(EnrichmentConfigError):
    """A credential exists but cannot be used now (expired, secrets unreadable, other resource).
    Its state has been recorded; the user has to reconnect."""


# --- pricing and view -----------------------------------------------------------------------


def pricing(settings: Settings) -> PricingOut:
    return PricingOut(
        email=DEFAULT_CREDIT_COSTS["email"],
        mobile=DEFAULT_CREDIT_COSTS["mobile"],
        ceiling=settings.enrichment_max_credits_per_call,
    )


def estimate_credits(want: list[str]) -> float:
    return sum(DEFAULT_CREDIT_COSTS.get(w, 0.0) for w in dict.fromkeys(want))


def status_view(session: Session, settings: Settings, ws: Workspace) -> ConnectorOut:
    cred = store.get_credential(session, ws.id)
    status = cred.status if cred is not None else "not_connected"
    if ws.is_demo:
        mode = "fake"
    else:
        mode = "tamtam" if status == "connected" else "off"
    tools = None
    if cred is not None and isinstance(cred.tools, list):
        tools = [ToolOut.model_validate(t) for t in cred.tools]
    return ConnectorOut(
        provider="tamtam",
        status=status,  # type: ignore[arg-type]
        enrichment_mode=mode,  # type: ignore[arg-type]
        secret_key_configured=key_configured(settings),
        resource=settings.tamtam_mcp_url,
        issuer=cred.issuer if cred else None,
        scope=cred.scope if cred else None,
        connected_at=cred.connected_at if cred else None,
        token_expires_at=cred.token_expires_at if cred else None,
        checked_at=cred.checked_at if cred else None,
        tools=tools,
        last_error=cred.last_error if cred else None,
        pricing=pricing(settings),
    )


# --- connect --------------------------------------------------------------------------------


async def start_connect(db: Session, settings: Settings, ws_id: uuid.UUID) -> tuple[str, str]:
    """(authorize_url, browser_secret). The secret goes into the `df_oauth` cookie."""
    seal("probe", settings)  # EnrichmentConfigError (hint: dataforce secrets init) when no key

    def load() -> tuple[str, str | None, str] | None:
        cred = store.get_credential(db, ws_id)
        snap = (cred.client_id, cred.client_secret_enc, cred.redirect_uri) if cred else None
        db.rollback()
        return snap

    existing = await run_in_threadpool(load)
    redirect_uri = oauth.redirect_uri_for(settings)
    async with oauth.new_client() as client:
        meta = await oauth.discover(client, settings)
        if existing is not None and existing[2] == redirect_uri and existing[0]:
            client_id, secret_enc = existing[0], existing[1]
        else:
            registered = await oauth.register_client(client, meta, redirect_uri)
            client_id = registered.client_id
            secret_enc = (
                seal(registered.client_secret, settings) if registered.client_secret else None
            )
    state = oauth.new_state()
    verifier, challenge = oauth.new_pkce()
    browser_secret = secrets.token_urlsafe(32)
    url = oauth.build_authorize_url(
        meta,
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        challenge=challenge,
        resource=settings.tamtam_mcp_url,
    )

    def save() -> None:
        store.create_pending(
            db,
            ws_id,
            state=state,
            browser_secret=browser_secret,
            verifier_enc=seal(verifier, settings),
            issuer=meta.issuer,
            resource=settings.tamtam_mcp_url,
            client_id=client_id,
            client_secret_enc=secret_enc,
            redirect_uri=redirect_uri,
        )
        db.commit()

    await run_in_threadpool(save)
    return url, browser_secret


@dataclass(frozen=True)
class CallbackResult:
    reason: str | None  # None: connected
    slug: str | None  # the workspace to send the browser back to, when known


async def finish_callback(
    db: Session,
    settings: Settings,
    *,
    state: str | None,
    code: str | None,
    iss: str | None,
    error: str | None,
    browser_cookie: str | None,
) -> CallbackResult:
    if not state or len(state) > MAX_STATE_CHARS:
        return CallbackResult(INVALID_STATE, None)

    def take() -> tuple[Any, str | None]:
        pending = store.take_pending(db, state)
        slug = None
        if pending is not None:
            slug = db.scalar(select(Workspace.slug).where(Workspace.id == pending.workspace_id))
        db.commit()  # the flow is spent whatever happens next
        return pending, slug

    pending, slug = await run_in_threadpool(take)
    if pending is None:
        return CallbackResult(INVALID_STATE, None)
    if pending.expires_at < datetime.now(UTC):
        return CallbackResult(EXPIRED, slug)
    if not browser_cookie or not hmac.compare_digest(
        store.sha256_hex(browser_cookie), pending.browser_hash
    ):
        return CallbackResult(INVALID_STATE, slug)
    if error:
        return CallbackResult(DENIED if error == "access_denied" else SERVER_ERROR, slug)
    if iss is not None and iss != pending.issuer:
        return CallbackResult(INVALID_STATE, slug)  # RFC 9207 mix-up defence
    if not code or len(code) > MAX_CODE_CHARS:
        return CallbackResult(EXCHANGE_FAILED, slug)
    try:
        if pending.resource.rstrip("/") != settings.tamtam_mcp_url.rstrip("/"):
            return CallbackResult(EXCHANGE_FAILED, slug)
        verifier = unseal(pending.code_verifier_enc, settings)
        secret = unseal(pending.client_secret_enc, settings) if pending.client_secret_enc else None
        async with oauth.new_client() as client:
            meta = await oauth.discover(client, settings)
            if meta.issuer != pending.issuer:
                return CallbackResult(EXCHANGE_FAILED, slug)
            if meta.iss_required and iss is None:
                return CallbackResult(INVALID_STATE, slug)
            tokens = await oauth.exchange_code(
                client,
                meta,
                client_id=pending.client_id,
                client_secret=secret,
                code=code,
                verifier=verifier,
                redirect_uri=pending.redirect_uri,
                resource=pending.resource,
            )

        def save() -> None:
            store.save_credential(
                db,
                pending.workspace_id,
                status="connected",
                issuer=pending.issuer,
                resource=pending.resource,
                client_id=pending.client_id,
                client_secret_enc=pending.client_secret_enc,
                redirect_uri=pending.redirect_uri,
                access_token_enc=seal(tokens.access_token, settings),
                refresh_token_enc=seal(tokens.refresh_token, settings)
                if tokens.refresh_token
                else None,
                token_expires_at=tokens.expires_at,
                scope=tokens.scope,
                tools=None,
                checked_at=None,
                last_error=None,
            )
            db.commit()

        await run_in_threadpool(save)
    except EnrichmentConfigError:
        return CallbackResult(SERVER_ERROR, slug)
    except EnrichmentError:
        return CallbackResult(EXCHANGE_FAILED, slug)
    except Exception as exc:  # noqa: BLE001 - the browser gets a fixed code, the log a class name
        log.error("tamtam callback failed (%s)", type(exc).__name__)
        db.rollback()
        return CallbackResult(SERVER_ERROR, slug)
    return CallbackResult(None, slug)


# --- using the stored token -----------------------------------------------------------------


@dataclass(frozen=True)
class _Snapshot:
    status: str
    issuer: str
    resource: str
    client_id: str
    client_secret_enc: str | None
    access_token_enc: str
    refresh_token_enc: str | None
    expires_at: datetime | None


_locks: dict[uuid.UUID, asyncio.Lock] = {}


def _snapshot(cred: ConnectorCredential) -> _Snapshot:
    return _Snapshot(
        cred.status,
        cred.issuer,
        cred.resource,
        cred.client_id,
        cred.client_secret_enc,
        cred.access_token_enc,
        cred.refresh_token_enc,
        cred.token_expires_at,
    )


async def _mark(db: Session, ws_id: uuid.UUID, status: str, message: str) -> None:
    def work() -> None:
        store.set_status(db, ws_id, status, message)
        db.commit()

    await run_in_threadpool(work)


async def access_token(db: Session, settings: Settings, ws_id: uuid.UUID) -> str:
    """A usable access token, refreshed first when it has less than 60 s left. A rotated refresh
    token replaces the old one. `invalid_grant` marks the credential `expired`."""
    lock = _locks.setdefault(ws_id, asyncio.Lock())
    async with lock:

        def load() -> _Snapshot | None:
            cred = store.get_credential(db, ws_id)
            snap = _snapshot(cred) if cred else None
            db.rollback()
            return snap

        snap = await run_in_threadpool(load)
        if snap is None:
            raise EnrichmentConfigError("TamTam is not connected for this workspace")
        if snap.resource.rstrip("/") != settings.tamtam_mcp_url.rstrip("/"):
            msg = "the stored connection is for a different TamTam URL; reconnect"
            await _mark(db, ws_id, "error", msg)
            raise ConnectorNotUsable(msg)
        if snap.status != "connected":
            raise ConnectorNotUsable(
                "the TamTam connection has expired; reconnect"
                if snap.status == "expired"
                else "the TamTam connection is in error; reconnect"
            )
        try:
            access = unseal(snap.access_token_enc, settings)
            refresh = unseal(snap.refresh_token_enc, settings) if snap.refresh_token_enc else None
            secret = unseal(snap.client_secret_enc, settings) if snap.client_secret_enc else None
        except UnsealError:
            msg = "stored secrets cannot be decrypted (the secret key changed); reconnect"
            await _mark(db, ws_id, "error", msg)
            raise ConnectorNotUsable(msg) from None
        if not oauth.needs_refresh(snap.expires_at):
            return access
        if not refresh:
            msg = "the access token expired and there is no refresh token; reconnect"
            await _mark(db, ws_id, "expired", msg)
            raise ConnectorNotUsable(msg)
        try:
            async with oauth.new_client() as client:
                meta = await oauth.discover(client, settings)
                if meta.issuer != snap.issuer:
                    raise oauth.OAuthError("the authorization server changed")
                tokens = await oauth.refresh_tokens(
                    client,
                    meta,
                    client_id=snap.client_id,
                    client_secret=secret,
                    refresh_token=refresh,
                    resource=snap.resource,
                )
        except oauth.InvalidGrant:
            msg = "the TamTam sign-in expired (invalid_grant); reconnect"
            await _mark(db, ws_id, "expired", msg)
            raise ConnectorNotUsable(msg) from None

        def save() -> None:
            store.update_tokens(
                db,
                ws_id,
                access_token_enc=seal(tokens.access_token, settings),
                refresh_token_enc=seal(tokens.refresh_token, settings)
                if tokens.refresh_token
                else None,
                token_expires_at=tokens.expires_at,
            )
            db.commit()

        await run_in_threadpool(save)
        return tokens.access_token


async def build_provider(db: Session, settings: Settings, ws_id: uuid.UUID) -> TamTamMCPEnrichment:
    token = await access_token(db, settings, ws_id)
    return TamTamMCPEnrichment(settings, token=token)


# --- check ----------------------------------------------------------------------------------

_NAME_RE = re.compile(r"[^\w.\-]")
_ALLOWED_TOOLS = frozenset(n.lower() for names in DEFAULT_TOOL_MAP.values() for n in names)


def tool_snapshot(tools: list[Any]) -> list[dict[str, Any]]:
    """What we keep of a server's tool list: sanitised, capped, with the allow-list verdict."""
    out: list[dict[str, Any]] = []
    for raw in tools[:MAX_TOOLS]:
        info = _tool_info(raw)
        hints = info.annotations or {}
        read_only, destructive = hints.get("readOnlyHint"), hints.get("destructiveHint")
        description = safe_server_text(info.description)[:TOOL_DESCRIPTION_CHARS]
        out.append(
            ToolOut(
                name=_NAME_RE.sub("?", info.name)[:64],
                description=description or None,
                read_only=read_only if isinstance(read_only, bool) else None,
                destructive=destructive if isinstance(destructive, bool) else None,
                allowed=info.name.lower() in _ALLOWED_TOOLS,
            ).model_dump()
        )
    return out


async def run_check(
    db: Session,
    settings: Settings,
    ws_id: uuid.UUID,
    *,
    session_factory: Callable[[str], AbstractAsyncContextManager[Any]] | None = None,
) -> None:
    """Open an MCP session and run `list_tools` only (never `call_tool`); store the snapshot.
    Expired / unreadable credentials are recorded and returned as such (no exception); a failed
    attempt is recorded in `last_error` and raised as an EnrichmentError (HTTP 502)."""
    try:
        token = await access_token(db, settings, ws_id)
    except ConnectorNotUsable:
        return
    opener = session_factory or (lambda t: open_http_session(settings.tamtam_mcp_url, t))
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_S):
            async with opener(token) as session:
                listed = list((await session.list_tools()).tools)
        snapshot = tool_snapshot(listed)
    except EnrichmentError as exc:
        text = safe_server_text(str(exc), [token])
        if "authentication rejected" in text:
            await _mark(db, ws_id, "expired", "TamTam rejected the access token; reconnect")
            return
        await _record_failure(db, ws_id, text)
        raise EnrichmentError(text) from None
    except Exception as exc:  # noqa: BLE001
        text = f"the connection check failed ({type(exc).__name__})"
        await _record_failure(db, ws_id, text)
        raise EnrichmentError(text) from None

    def save() -> None:
        store.record_check(db, ws_id, tools=snapshot, last_error=None)
        db.commit()

    await run_in_threadpool(save)


async def _record_failure(db: Session, ws_id: uuid.UUID, text: str) -> None:
    def work() -> None:
        store.record_check(db, ws_id, tools=None, last_error=text)
        db.commit()

    await run_in_threadpool(work)


# --- disconnect -----------------------------------------------------------------------------


async def disconnect(db: Session, settings: Settings, ws_id: uuid.UUID) -> None:
    """Delete the credential and pending rows, then revoke (RFC 7009) if the server advertises
    an endpoint. Revocation is best effort and never blocks or fails the disconnect."""

    def work() -> _Snapshot | None:
        cred = store.get_credential(db, ws_id)
        snap = _snapshot(cred) if cred else None
        store.delete_credential(db, ws_id)
        db.commit()
        return snap

    snap = await run_in_threadpool(work)
    if snap is None:
        return
    try:
        token = unseal(snap.refresh_token_enc or snap.access_token_enc, settings)
        async with oauth.new_client() as client:
            meta = await oauth.discover(client, settings)
            if meta.issuer == snap.issuer:
                await oauth.revoke_token(client, meta, token, snap.client_id)
    except Exception as exc:  # noqa: BLE001
        log.info("tamtam revocation skipped (%s)", type(exc).__name__)
