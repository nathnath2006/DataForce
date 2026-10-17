from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.domain.enums import RunKind, RunStatus
from app.domain.schemas import LLMCallRecord
from app.services import admin, llm_usage, runs, workspaces
from app.services.errors import InvalidInputError, NotFoundError

pytestmark = pytest.mark.integration


def test_run_lifecycle(db_session: Session, ws_id):
    run = runs.start_run(db_session, RunKind.STATS_SCAN, ws_id, {"seed": 1, "t": "a\x00b"})
    assert run.status == "running" and run.params == {"seed": 1, "t": "ab"}
    runs.finish_run(db_session, run, RunStatus.SUCCEEDED, {"n": 3})
    assert run.status == "succeeded" and run.result == {"n": 3} and run.duration_ms >= 0
    failed = runs.start_run(db_session, "demo_generate", workspace_id=ws_id)
    runs.finish_run(db_session, failed.id, RunStatus.FAILED, error="boom\x00", ws_id=ws_id)
    assert failed.error == "boom"
    assert runs.list_runs(db_session, ws_id, kind=RunKind.STATS_SCAN) == [run]
    assert runs.get_run(db_session, ws_id, run.id) is run
    with pytest.raises(NotFoundError):
        runs.finish_run(db_session, uuid.uuid4(), RunStatus.FAILED, ws_id=ws_id)
    with pytest.raises(InvalidInputError):
        runs.start_run(db_session, RunKind.STATS_SCAN)


def test_runs_and_usage_are_workspace_scoped(db_session: Session, ws_id, session_factory):
    other = workspaces.create_workspace(db_session, "other-ws", "Other").id
    run = runs.start_run(db_session, RunKind.STATS_SCAN, ws_id)
    assert runs.get_run(db_session, other, run.id) is None
    assert runs.list_runs(db_session, other) == []
    with pytest.raises(NotFoundError):
        runs.finish_run(db_session, run.id, RunStatus.FAILED, ws_id=other)
    call = LLMCallRecord(
        provider="fake",
        model="m",
        purpose="explanation",
        latency_ms=1,
        success=True,
        input_tokens=1,
    )
    llm_usage.DbUsageRecorder(session_factory, workspace_id=ws_id, run_id=run.id).record(call)
    assert llm_usage.usage_summary(db_session, other) == []
    assert llm_usage.usage_summary(db_session, ws_id)[0]["calls"] == 1


def test_usage_recorder_and_summary(db_session: Session, session_factory, ws_id):
    run = runs.start_run(db_session, RunKind.STATS_SCAN, ws_id)
    rec = llm_usage.DbUsageRecorder(session_factory, workspace_id=ws_id, run_id=run.id)
    rec.record(
        LLMCallRecord(
            provider="fake",
            model="m",
            purpose="explanation",
            input_tokens=5,
            output_tokens=7,
            latency_ms=3,
            success=True,
        )
    )
    summary = llm_usage.usage_summary(db_session, ws_id, run.id)
    assert summary[0]["calls"] == 1 and summary[0]["input_tokens"] == 5


def test_db_size(db_session: Session):
    info = admin.db_size(db_session, 500)
    assert info["size_bytes"] > 0 and info["quota_mb"] == 500
    assert "workspace" in {t["name"] for t in info["tables"]}
