"""Database access for connector credentials and OAuth flows in flight (sync, short).

Nothing here commits: the caller owns the transaction. Nothing here talks to the network.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import ConnectorCredential, OAuthPending

PROVIDER = "tamtam"
PENDING_TTL = timedelta(minutes=10)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def get_credential(session: Session, ws_id: uuid.UUID) -> ConnectorCredential | None:
    return session.scalar(
        select(ConnectorCredential).where(
            ConnectorCredential.workspace_id == ws_id, ConnectorCredential.provider == PROVIDER
        )
    )


def save_credential(session: Session, ws_id: uuid.UUID, **fields: Any) -> ConnectorCredential:
    """Create or replace the workspace's credential (a reconnect clears the old tool snapshot)."""
    cred = get_credential(session, ws_id)
    if cred is None:
        cred = ConnectorCredential(workspace_id=ws_id, provider=PROVIDER, **fields)
        session.add(cred)
    else:
        for key, value in fields.items():
            setattr(cred, key, value)
        cred.connected_at = datetime.now(UTC)
    session.flush()
    return cred


_LOCK_NS = 7_461_220_007


def lock_connector(session: Session, ws_id: uuid.UUID) -> None:
    """Transaction-level advisory lock on (workspace, provider): token refresh writes, callback
    saves and disconnect run one after the other, across processes. Released at commit/rollback."""
    session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(f"{ws_id}:{PROVIDER}", _LOCK_NS)))
    )


def update_tokens(
    session: Session,
    ws_id: uuid.UUID,
    *,
    access_token_enc: str,
    refresh_token_enc: str | None,
    token_expires_at: datetime | None,
    expected_connected_at: datetime,
    expected_access_token_enc: str,
) -> bool:
    """Store refreshed tokens only if the credential is still the one the refresh started from
    (same `connected_at`, same access token). Returns False when a reconnect, another refresh or
    a disconnect got there first: the caller then drops its tokens. Call under `lock_connector`."""
    cred = get_credential(session, ws_id)
    if (
        cred is None
        or cred.connected_at != expected_connected_at
        or cred.access_token_enc != expected_access_token_enc
    ):
        return False
    cred.access_token_enc = access_token_enc
    cred.refresh_token_enc = refresh_token_enc
    cred.token_expires_at = token_expires_at
    cred.status = "connected"
    cred.last_error = None
    session.flush()
    return True


def set_status(session: Session, ws_id: uuid.UUID, status: str, last_error: str | None) -> None:
    cred = get_credential(session, ws_id)
    if cred is not None:
        cred.status = status
        cred.last_error = last_error
        session.flush()


def record_check(
    session: Session,
    ws_id: uuid.UUID,
    *,
    tools: list[dict[str, Any]] | None,
    last_error: str | None,
) -> None:
    cred = get_credential(session, ws_id)
    if cred is not None:
        if tools is not None:
            cred.tools = tools
            cred.checked_at = datetime.now(UTC)
        cred.last_error = last_error
        session.flush()


def delete_credential(session: Session, ws_id: uuid.UUID) -> None:
    session.execute(
        delete(ConnectorCredential).where(
            ConnectorCredential.workspace_id == ws_id, ConnectorCredential.provider == PROVIDER
        )
    )
    session.execute(
        delete(OAuthPending).where(
            OAuthPending.workspace_id == ws_id, OAuthPending.provider == PROVIDER
        )
    )
    session.expire_all()


def purge_expired_pending(session: Session) -> int:
    result = session.execute(delete(OAuthPending).where(OAuthPending.expires_at < func.now()))
    return result.rowcount or 0


def create_pending(
    session: Session,
    ws_id: uuid.UUID,
    *,
    state: str,
    browser_secret: str,
    verifier_enc: str,
    issuer: str,
    resource: str,
    client_id: str,
    client_secret_enc: str | None,
    redirect_uri: str,
) -> None:
    """One flow in flight per workspace: starting again drops the previous one."""
    purge_expired_pending(session)
    session.execute(
        delete(OAuthPending).where(
            OAuthPending.workspace_id == ws_id, OAuthPending.provider == PROVIDER
        )
    )
    session.add(
        OAuthPending(
            workspace_id=ws_id,
            provider=PROVIDER,
            state_hash=sha256_hex(state),
            browser_hash=sha256_hex(browser_secret),
            code_verifier_enc=verifier_enc,
            issuer=issuer,
            resource=resource,
            client_id=client_id,
            client_secret_enc=client_secret_enc,
            redirect_uri=redirect_uri,
            expires_at=datetime.now(UTC) + PENDING_TTL,
        )
    )
    session.flush()


def take_pending(session: Session, state: str) -> OAuthPending | None:
    """Single use: the row is deleted whatever happens next and returned detached. The caller
    checks `expires_at` (an expired flow is reported as "expired", not as an unknown state)."""
    # One atomic statement: two concurrent callbacks with the same state cannot both get the row.
    pending = session.execute(
        delete(OAuthPending)
        .where(OAuthPending.state_hash == sha256_hex(state))
        .returning(OAuthPending)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    if pending is not None:
        session.expunge(pending)
    return pending
