"""Uploaded CSV / XLSX files for analysis flows (stored in the database)."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from app.config import Settings
from app.db.models import UploadedFile
from app.flows.sources import files as parsing
from app.flows.sources.frame import column_infos
from app.services import limits as limits_service
from app.services._common import get_scoped
from app.services.errors import InvalidInputError, NotFoundError


def create_file(
    db: Session,
    ws_id: uuid.UUID,
    filename: str | None,
    data: bytes,
    sheet: str | None,
    settings: Settings,
) -> UploadedFile:
    settings = limits_service.effective_settings(db, settings, ws_id)
    name = parsing.sanitize_name(filename)
    if not data:
        raise InvalidInputError("the file is empty")
    if len(data) > settings.upload_max_bytes:
        raise InvalidInputError(f"the file is larger than {settings.upload_max_bytes} bytes")
    try:
        parsed = parsing.parse_file(
            name,
            data,
            cap_bytes=settings.upload_max_bytes,
            max_rows=settings.flow_max_rows,
            sheet=sheet,
        )
    except parsing.UploadRefused as exc:
        raise InvalidInputError(str(exc)) from None
    if parsed.frame.attrs.get("capped"):
        raise InvalidInputError(f"the file has more than {settings.flow_max_rows} rows")
    row = UploadedFile(
        workspace_id=ws_id,
        name=name,
        media_type=parsed.media_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        content=data,
        sheet=parsed.sheet,
        n_rows=len(parsed.frame),
        columns=column_infos(parsed.frame),
    )
    db.add(row)
    db.flush()
    return row


def list_files(db: Session, ws_id: uuid.UUID) -> list[UploadedFile]:
    stmt = (
        select(UploadedFile)
        .options(defer(UploadedFile.content))
        .where(UploadedFile.workspace_id == ws_id)
        .order_by(UploadedFile.created_at.desc())
    )
    return list(db.scalars(stmt))


def require_file(db: Session, ws_id: uuid.UUID, file_id: uuid.UUID) -> UploadedFile:
    row = get_scoped(db, UploadedFile, ws_id, file_id)
    if row is None:
        raise NotFoundError("file not found")
    return row


def delete_file(db: Session, ws_id: uuid.UUID, file_id: uuid.UUID) -> None:
    db.delete(require_file(db, ws_id, file_id))
    db.flush()
