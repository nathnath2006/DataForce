"""Run history (demo loads, stats scans)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Run
from app.domain.enums import RunKind, RunStatus
from app.services.errors import InvalidInputError, NotFoundError
from app.services.textclean import scrub_json, scrub_text

_ERROR_MAX_CHARS = 4000


def _jsonable(value: Any) -> Any:
    """Plain JSON data, scrubbed. A pydantic model (e.g. a ScanReport) is dumped in JSON mode."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return scrub_json(value)


def start_run(
    session: Session,
    kind: RunKind | str,
    ws_id: uuid.UUID | None = None,
    params: dict[str, Any] | None = None,
    *,
    workspace_id: uuid.UUID | None = None,
) -> Run:
    """A run always belongs to a workspace. `workspace_id` is a keyword alias of `ws_id`
    (either spelling works, one of them is required)."""
    ws_id = ws_id or workspace_id
    if ws_id is None:
        raise InvalidInputError("a run needs a workspace id")
    # started_at is set from Python: Postgres now() is the *transaction* start, which would be
    # wrong for a run whose row is created at the top of a long transaction.
    run = Run(
        workspace_id=ws_id,
        kind=str(getattr(kind, "value", kind)),
        status=RunStatus.RUNNING.value,
        params=_jsonable(params or {}),
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    return run


def finish_run(
    session: Session,
    run: Run | uuid.UUID,
    status: RunStatus,
    result: dict[str, Any] | BaseModel | None = None,
    error: str | None = None,
    *,
    ws_id: uuid.UUID | None = None,
) -> Run:
    """Close a run. Accepts the run, or its id together with `ws_id` (so it works across
    transactions/sessions); a run of another workspace is "not found"."""
    if isinstance(run, Run):
        run_id, ws_id = run.id, run.workspace_id
    else:
        run_id = run
        if ws_id is None:
            raise InvalidInputError("finish_run by id needs ws_id")
    row = get_run(session, ws_id, run_id)
    if row is None:
        raise NotFoundError(f"run {run_id} not found in this workspace")
    finished = datetime.now(UTC)
    row.status = status.value
    row.finished_at = finished
    row.duration_ms = max(0, int((finished - row.started_at).total_seconds() * 1000))
    row.result = None if result is None else _jsonable(result)
    row.error = scrub_text(error)[:_ERROR_MAX_CHARS] if error else None
    session.flush()
    return row


def get_run(session: Session, ws_id: uuid.UUID, run_id: uuid.UUID) -> Run | None:
    """The run only when it belongs to `ws_id`."""
    row = session.get(Run, run_id)
    if row is None or row.workspace_id != ws_id:
        return None
    return row


def list_runs(
    session: Session,
    ws_id: uuid.UUID,
    *,
    kind: RunKind | str | None = None,
    limit: int = 20,
) -> list[Run]:
    stmt = select(Run).where(Run.workspace_id == ws_id).order_by(Run.started_at.desc())
    if kind is not None:
        stmt = stmt.where(Run.kind == str(getattr(kind, "value", kind)))
    return list(session.scalars(stmt.limit(limit)))
