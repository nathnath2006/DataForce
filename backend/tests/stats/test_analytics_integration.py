"""analytics service on a tiny ORM-inserted dataset (needs the test database)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.models import Account, AppUser, Deal, Run, Workspace
from app.domain.enums import Metric, RunKind
from app.domain.schemas import GateConfig
from app.services.analytics import load_deal_rows, pipeline_summary, run_scan

pytestmark = pytest.mark.integration


def _seed(session: Session) -> Workspace:
    ws = Workspace(slug="stats-it", name="Stats IT", is_demo=True)
    session.add(ws)
    session.flush()
    rep = AppUser(workspace_id=ws.id, display_name="Ana")
    acc = Account(workspace_id=ws.id, name="Acme", industry="saas", segment="smb", region="north")
    acc_bare = Account(workspace_id=ws.id, name="Bare")
    session.add_all([rep, acc, acc_bare])
    session.flush()

    def deal(name, account, stage, amount, owner=rep, src="inbound", closed=None):
        return Deal(
            workspace_id=ws.id,
            account_id=account.id,
            owner_id=owner.id if owner else None,
            name=name,
            stage=stage,
            amount_eur=amount,
            lead_source=src,
            created_on=date(2025, 1, 1),
            closed_on=closed,
        )

    session.add_all(
        [
            deal("won1", acc, "closed_won", Decimal("12000.50"), closed=date(2025, 1, 31)),
            deal("won2", acc, "closed_won", Decimal("60000"), closed=date(2025, 2, 10)),
            deal("lost1", acc, "closed_lost", None, closed=date(2025, 1, 15)),
            deal("lost_noclose", acc_bare, "closed_lost", Decimal("500"), owner=None, src=None),
            deal("open1", acc_bare, "proposal", Decimal("8000")),
        ]
    )
    session.flush()
    return ws


def test_load_rows_join(db_session: Session) -> None:
    ws = _seed(db_session)
    rows = {r.stage + str(i): r for i, r in enumerate(load_deal_rows(db_session, ws.id))}
    assert len(rows) == 5
    won1 = next(r for r in rows.values() if r.amount == 12000.5)
    assert won1.won is True and won1.cycle_days == 30 and won1.owner == "Ana"
    assert (won1.segment, won1.industry, won1.region) == ("smb", "saas", "north")
    bare = next(r for r in rows.values() if r.amount == 500)
    assert bare.owner is None and bare.segment is None and bare.won is False
    assert bare.cycle_days is None


def test_pipeline_summary_exact(db_session: Session) -> None:
    ws = _seed(db_session)
    s = pipeline_summary(db_session, ws.id)
    assert (s["n_deals"], s["n_open"], s["n_closed"], s["n_won"], s["n_lost"]) == (5, 1, 4, 2, 2)
    assert s["by_stage"]["closed_won"]["amount_eur"] == 72000.5
    assert s["by_stage"]["proposal"]["count"] == 1
    assert s["by_stage"]["prospecting"]["count"] == 0
    assert s["total_amount_eur"] == 80500.5


def test_run_scan_persists_run(db_session: Session) -> None:
    ws = _seed(db_session)
    report = run_scan(db_session, ws.id, GateConfig(bootstrap_resamples=200))
    assert report.n_deals == 5 and report.workspace_id == ws.id
    assert report.overall[Metric.WIN_RATE].n == 4
    assert report.missing["closed_on"] == 1
    run = db_session.query(Run).filter_by(workspace_id=ws.id).one()
    assert run.kind == RunKind.STATS_SCAN.value and run.status == "succeeded"
    assert run.result is not None and run.result["n_deals"] == 5
    assert run.finished_at is not None
