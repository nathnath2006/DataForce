"""SYS-05: runs left "running" by a stopped app are closed at the next start."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.domain.enums import RunKind, RunStatus
from app.services import runs, workspaces

pytestmark = pytest.mark.integration


def test_reaper_closes_only_old_running_runs(db_session: Session):
    ws = workspaces.create_workspace(db_session, "reaper-test", "Reaper")
    old = runs.start_run(db_session, RunKind.STATS_SCAN, ws.id)
    old.started_at = datetime.now(UTC) - runs.STALE_RUN_AFTER - timedelta(minutes=1)
    fresh = runs.start_run(db_session, RunKind.STATS_SCAN, ws.id)
    done = runs.start_run(db_session, RunKind.STATS_SCAN, ws.id)
    done.status = RunStatus.SUCCEEDED.value
    done.started_at = old.started_at
    db_session.flush()

    assert runs.reap_stale_runs(db_session) >= 1
    db_session.refresh(old)
    db_session.refresh(fresh)
    db_session.refresh(done)
    assert old.status == RunStatus.FAILED.value
    assert old.error == runs.INTERRUPTED_ERROR
    assert old.finished_at is not None
    assert fresh.status == RunStatus.RUNNING.value
    assert done.status == RunStatus.SUCCEEDED.value
