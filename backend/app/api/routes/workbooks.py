"""Workbook CRUD (M4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from app.api.deps import CurrentWorkspace, Db
from app.api.schemas_viz import (
    WorkbookCreate,
    WorkbookOut,
    WorkbookSummary,
    WorkbookUpdate,
)
from app.db.models import Workbook
from app.services import workbooks

router = APIRouter(tags=["workbooks"])


def _out(row: Workbook) -> WorkbookOut:
    return WorkbookOut(
        id=row.id,
        name=row.name,
        spec=workbooks.parse_stored(row.spec),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/w/{ws}/workbooks", response_model=list[WorkbookSummary])
def list_workbooks(db: Db, ws: CurrentWorkspace) -> list[WorkbookSummary]:
    return [
        WorkbookSummary(
            id=w.id, name=w.name, n_canvases=workbooks.n_canvases(w.spec), updated_at=w.updated_at
        )
        for w in workbooks.list_workbooks(db, ws.id)
    ]


@router.post("/w/{ws}/workbooks", response_model=WorkbookOut, status_code=201)
def create_workbook(body: WorkbookCreate, db: Db, ws: CurrentWorkspace) -> WorkbookOut:
    row = workbooks.create(db, ws.id, body.name, body.spec)
    db.commit()
    return _out(row)


@router.get("/w/{ws}/workbooks/{wb_id}", response_model=WorkbookOut)
def get_workbook(wb_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> WorkbookOut:
    return _out(workbooks.require(db, ws.id, wb_id))


@router.patch("/w/{ws}/workbooks/{wb_id}", response_model=WorkbookOut)
def update_workbook(
    wb_id: uuid.UUID, body: WorkbookUpdate, db: Db, ws: CurrentWorkspace
) -> WorkbookOut:
    row = workbooks.update(db, ws.id, wb_id, body.name, body.spec)
    db.commit()
    return _out(row)


@router.post("/w/{ws}/workbooks/{wb_id}/duplicate", response_model=WorkbookOut, status_code=201)
def duplicate_workbook(wb_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> WorkbookOut:
    row = workbooks.duplicate(db, ws.id, wb_id)
    db.commit()
    return _out(row)


@router.delete("/w/{ws}/workbooks/{wb_id}", status_code=204)
def delete_workbook(wb_id: uuid.UUID, db: Db, ws: CurrentWorkspace) -> Response:
    workbooks.delete(db, ws.id, wb_id)
    db.commit()
    return Response(status_code=204)
