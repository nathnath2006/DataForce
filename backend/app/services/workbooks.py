"""Saved visual workbooks (M4). The spec is validated by pydantic before it is stored."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas_viz import WorkbookSpec
from app.db.models import Workbook
from app.services._common import get_scoped
from app.services.errors import NotFoundError


def dump_spec(spec: WorkbookSpec) -> dict[str, Any]:
    return spec.model_dump(mode="json")


def parse_stored(raw: dict[str, Any] | None) -> WorkbookSpec:
    return WorkbookSpec.model_validate(raw or {})


def n_canvases(raw: dict[str, Any] | None) -> int:
    return len((raw or {}).get("canvases", []))


def list_workbooks(db: Session, ws_id: uuid.UUID) -> list[Workbook]:
    stmt = (
        select(Workbook)
        .where(Workbook.workspace_id == ws_id)
        .order_by(Workbook.updated_at.desc(), Workbook.id)
    )
    return list(db.scalars(stmt))


def require(db: Session, ws_id: uuid.UUID, wb_id: uuid.UUID) -> Workbook:
    row = get_scoped(db, Workbook, ws_id, wb_id)
    if row is None:
        raise NotFoundError("workbook not found")
    return row


def create(db: Session, ws_id: uuid.UUID, name: str, spec: WorkbookSpec) -> Workbook:
    row = Workbook(workspace_id=ws_id, name=name, spec=dump_spec(spec))
    db.add(row)
    db.flush()
    db.refresh(row)
    return row


def update(
    db: Session, ws_id: uuid.UUID, wb_id: uuid.UUID, name: str | None, spec: WorkbookSpec | None
) -> Workbook:
    row = require(db, ws_id, wb_id)
    if name is not None:
        row.name = name
    if spec is not None:
        row.spec = dump_spec(spec)
    db.flush()
    db.refresh(row)
    return row


def duplicate(db: Session, ws_id: uuid.UUID, wb_id: uuid.UUID) -> Workbook:
    src = require(db, ws_id, wb_id)
    suffix = " (copy)"
    return create(db, ws_id, src.name[: 200 - len(suffix)] + suffix, parse_stored(src.spec))


def delete(db: Session, ws_id: uuid.UUID, wb_id: uuid.UUID) -> None:
    db.delete(require(db, ws_id, wb_id))
    db.flush()
