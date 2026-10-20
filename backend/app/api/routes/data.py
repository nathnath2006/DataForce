"""Uploaded files and external PostgreSQL connections (docs/M2A-CONTRACT.md section 4)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, Response, UploadFile

from app.api.deps import AppSettings, CurrentViewer, CurrentWorkspace, Db
from app.api.schemas_flows import (
    ConnectionIn,
    ConnectionOut,
    ConnectionPatch,
    FileOut,
    TableRef,
)
from app.auth import demo
from app.auth.demo import NotDemo
from app.auth.visibility import require_admin
from app.db.models import DataConnection
from app.flows.ports import SourceError
from app.services import data_connections as conns
from app.services import files as file_service
from app.services.errors import InvalidInputError

router = APIRouter(tags=["data"])


# --- files ----------------------------------------------------------------------------------------
@router.post("/w/{ws}/files", response_model=FileOut, status_code=201)
def upload_file(
    request: Request,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    viewer: CurrentViewer,
    file: Annotated[UploadFile, File()],
    sheet: Annotated[str | None, Form(max_length=200)] = None,
) -> FileOut:
    require_admin(viewer)
    cap = demo.upload_cap(request, settings.upload_max_bytes, demo.client_address(request))
    data = file.file.read(cap + 1)
    demo.enforce_size(request, data)
    row = file_service.create_file(db, ws.id, file.filename, data, sheet or None, settings)
    db.commit()
    return FileOut.model_validate(row)


@router.get("/w/{ws}/files", response_model=list[FileOut])
def list_files(db: Db, ws: CurrentWorkspace, viewer: CurrentViewer) -> list[FileOut]:
    require_admin(viewer)
    return [FileOut.model_validate(f) for f in file_service.list_files(db, ws.id)]


@router.delete("/w/{ws}/files/{file_id}", status_code=204)
def delete_file(
    file_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> Response:
    require_admin(viewer)
    file_service.delete_file(db, ws.id, file_id)
    db.commit()
    return Response(status_code=204)


# --- connections ----------------------------------------------------------------------------------
def _conn_out(row: DataConnection) -> ConnectionOut:
    return ConnectionOut(
        id=row.id,
        name=row.name,
        host=row.host,
        port=row.port,
        database=row.database,
        username=row.username,
        sslmode=row.sslmode,
        has_password=row.password_enc is not None,
        last_test_at=row.last_test_at,
        last_test_ok=row.last_test_ok,
        last_error=row.last_error,
        created_at=row.created_at,
    )


def _plain(body: ConnectionIn | ConnectionPatch, *, partial: bool) -> dict:
    data = body.model_dump(exclude_unset=partial, exclude={"password"})
    if "host" in data and data["host"]:
        data["host"] = data["host"].strip("[]")  # libpq wants ::1, not [::1]
    secret = body.password.get_secret_value() if body.password else ""
    if secret or not partial:
        data["password"] = secret or None
    if partial:
        data = {k: v for k, v in data.items() if v is not None}
    return data


@router.get("/w/{ws}/connections", response_model=list[ConnectionOut])
def list_connections(db: Db, ws: CurrentWorkspace, viewer: CurrentViewer) -> list[ConnectionOut]:
    require_admin(viewer)
    return [_conn_out(c) for c in conns.list_connections(db, ws.id)]


@router.post(
    "/w/{ws}/connections", response_model=ConnectionOut, status_code=201, dependencies=[NotDemo]
)
def create_connection(
    body: ConnectionIn, db: Db, ws: CurrentWorkspace, settings: AppSettings, viewer: CurrentViewer
) -> ConnectionOut:
    require_admin(viewer)
    row = conns.create_connection(db, ws.id, _plain(body, partial=False), settings)
    db.commit()
    return _conn_out(row)


@router.patch(
    "/w/{ws}/connections/{connection_id}", response_model=ConnectionOut, dependencies=[NotDemo]
)
def update_connection(
    connection_id: uuid.UUID,
    body: ConnectionPatch,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    viewer: CurrentViewer,
) -> ConnectionOut:
    require_admin(viewer)
    row = conns.update_connection(db, ws.id, connection_id, _plain(body, partial=True), settings)
    db.commit()
    return _conn_out(row)


@router.delete("/w/{ws}/connections/{connection_id}", status_code=204, dependencies=[NotDemo])
def delete_connection(
    connection_id: uuid.UUID, db: Db, ws: CurrentWorkspace, viewer: CurrentViewer
) -> Response:
    require_admin(viewer)
    conns.delete_connection(db, ws.id, connection_id)
    db.commit()
    return Response(status_code=204)


@router.post(
    "/w/{ws}/connections/{connection_id}/test", response_model=ConnectionOut, dependencies=[NotDemo]
)
def test_connection(
    connection_id: uuid.UUID,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    viewer: CurrentViewer,
) -> ConnectionOut:
    require_admin(viewer)
    row = conns.test_connection(db, ws.id, connection_id, settings)
    db.commit()
    return _conn_out(row)


@router.get("/w/{ws}/connections/{connection_id}/tables", response_model=list[TableRef])
def connection_tables(
    connection_id: uuid.UUID,
    db: Db,
    ws: CurrentWorkspace,
    settings: AppSettings,
    viewer: CurrentViewer,
) -> list[dict[str, str]]:
    require_admin(viewer)
    try:
        return conns.tables_of(db, ws.id, connection_id, settings)
    except SourceError as exc:
        raise InvalidInputError(str(exc)) from None
