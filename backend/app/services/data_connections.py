"""External PostgreSQL connections (read-only; the password is sealed and never returned)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.connectors.crypto import UnsealError, seal, unseal
from app.db.models import DataConnection
from app.flows.ports import SourceError
from app.flows.sources import postgres
from app.services._common import get_scoped
from app.services.errors import AlreadyExistsError, InvalidInputError, NotFoundError

_TARGET_FIELDS = ("host", "port", "database", "username", "sslmode")


def _check_tls(host: str, sslmode: str) -> None:
    try:
        postgres.check_tls_policy(host, sslmode)
    except SourceError as exc:
        raise InvalidInputError(str(exc)) from None


def list_connections(db: Session, ws_id: uuid.UUID) -> list[DataConnection]:
    stmt = (
        select(DataConnection)
        .where(DataConnection.workspace_id == ws_id)
        .order_by(DataConnection.name)
    )
    return list(db.scalars(stmt))


def require_connection(db: Session, ws_id: uuid.UUID, connection_id: uuid.UUID) -> DataConnection:
    row = get_scoped(db, DataConnection, ws_id, connection_id)
    if row is None:
        raise NotFoundError("connection not found")
    return row


def _name_taken(db: Session, ws_id: uuid.UUID, name: str, except_id: uuid.UUID | None) -> bool:
    stmt = select(DataConnection.id).where(
        DataConnection.workspace_id == ws_id, DataConnection.name == name
    )
    found = db.scalar(stmt)
    return found is not None and found != except_id


def create_connection(
    db: Session, ws_id: uuid.UUID, data: dict, settings: Settings
) -> DataConnection:
    _check_tls(data["host"], data["sslmode"])
    if _name_taken(db, ws_id, data["name"], None):
        raise AlreadyExistsError("a connection with this name already exists")
    password = data.pop("password", None)
    row = DataConnection(
        workspace_id=ws_id,
        kind="postgres",
        password_enc=seal(password, settings) if password else None,
        **data,
    )
    db.add(row)
    db.flush()
    return row


def update_connection(
    db: Session, ws_id: uuid.UUID, connection_id: uuid.UUID, changes: dict, settings: Settings
) -> DataConnection:
    row = require_connection(db, ws_id, connection_id)
    password = changes.pop("password", None)  # empty / missing keeps the stored one
    host = changes.get("host", row.host)
    sslmode = changes.get("sslmode", row.sslmode)
    _check_tls(host, sslmode)
    moved = any(k in changes and changes[k] != getattr(row, k) for k in _TARGET_FIELDS)
    if moved and not password and row.password_enc:
        # the stored password must never be sent to another server or as another user
        raise InvalidInputError("re-enter the password when changing the server or user")
    if "name" in changes and _name_taken(db, ws_id, changes["name"], row.id):
        raise AlreadyExistsError("a connection with this name already exists")
    for key, value in changes.items():
        setattr(row, key, value)
    if password:
        row.password_enc = seal(password, settings)
    row.last_test_at = row.last_test_ok = row.last_error = None  # the old test no longer applies
    db.flush()
    return row


def delete_connection(db: Session, ws_id: uuid.UUID, connection_id: uuid.UUID) -> None:
    db.delete(require_connection(db, ws_id, connection_id))
    db.flush()


def target_of(row: DataConnection, settings: Settings) -> postgres.PgTarget:
    try:
        password = unseal(row.password_enc, settings) if row.password_enc else None
    except UnsealError:
        raise SourceError(
            "the stored password cannot be decrypted (was DATAFORCE_SECRET_KEY changed?); "
            "edit the connection and enter the password again"
        ) from None
    return postgres.PgTarget(
        host=row.host,
        port=row.port,
        database=row.database,
        username=row.username,
        password=password,
        sslmode=row.sslmode,
        timeout_s=settings.data_connection_timeout_s,
    )


def test_connection(
    db: Session, ws_id: uuid.UUID, connection_id: uuid.UUID, settings: Settings
) -> DataConnection:
    row = require_connection(db, ws_id, connection_id)
    row.last_test_at = datetime.now(UTC)
    try:
        postgres.check_connection(target_of(row, settings))
        row.last_test_ok, row.last_error = True, None
    except SourceError as exc:
        row.last_test_ok, row.last_error = False, str(exc)[:500]
    db.flush()
    return row


def tables_of(
    db: Session, ws_id: uuid.UUID, connection_id: uuid.UUID, settings: Settings
) -> list[dict[str, str]]:
    row = require_connection(db, ws_id, connection_id)
    return postgres.list_tables(target_of(row, settings))
