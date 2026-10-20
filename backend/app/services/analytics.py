"""Database side of the stats engine: load rows, exact pipeline aggregates, persisted scans.

`run_scan` records its run through `app.services.runs`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import visibility
from app.auth.viewer import Viewer
from app.config import get_settings
from app.db.models import Account, AppUser, Deal
from app.domain.enums import CLOSED_STAGES, OPEN_STAGES, DealStage, RunKind, RunStatus
from app.domain.schemas import GateConfig, ScanReport
from app.services import runs
from app.stats.engine import gate_config_from_settings, scan
from app.stats.rows import DealRow, won_from_stage


def load_deal_rows(
    session: Session, ws_id: uuid.UUID, viewer: Viewer | None = None
) -> list[DealRow]:
    """The deals the viewer may see, flattened with account and owner (one SQL join)."""
    stmt = (
        select(
            Deal.id,
            Deal.stage,
            Deal.lead_source,
            Deal.amount_eur,
            Deal.created_on,
            Deal.closed_on,
            Account.segment,
            Account.industry,
            Account.region,
            AppUser.display_name,
        )
        .join(Account, Account.id == Deal.account_id)
        .outerjoin(AppUser, AppUser.id == Deal.owner_id)
        .where(Deal.workspace_id == ws_id, *visibility.conds(visibility.deals_cond(viewer)))
        .order_by(Deal.created_on, Deal.id)
    )
    return [
        DealRow(
            id=r.id,
            won=won_from_stage(r.stage),
            stage=r.stage,
            lead_source=r.lead_source,
            segment=r.segment,
            industry=r.industry,
            region=r.region,
            owner=r.display_name,
            amount=float(r.amount_eur) if r.amount_eur is not None else None,
            created_on=r.created_on,
            closed_on=r.closed_on,
        )
        for r in session.execute(stmt)
    ]


def pipeline_summary(
    session: Session, ws_id: uuid.UUID, viewer: Viewer | None = None
) -> dict[str, Any]:
    """Exact SQL aggregates by stage (counts, amount sums). Facts: no CI."""
    stmt = (
        select(
            Deal.stage,
            func.count(Deal.id),
            func.coalesce(func.sum(Deal.amount_eur), 0),
            func.count(Deal.amount_eur),
        )
        .where(Deal.workspace_id == ws_id, *visibility.conds(visibility.deals_cond(viewer)))
        .group_by(Deal.stage)
    )
    found = {s: (c, float(a), ca) for s, c, a, ca in session.execute(stmt)}
    by_stage: dict[str, dict[str, Any]] = {}
    for stage in DealStage:
        c, a, ca = found.get(stage.value, (0, 0.0, 0))
        by_stage[stage.value] = {"count": c, "amount_eur": a, "n_with_amount": ca}
    count = lambda stages: sum(by_stage[s.value]["count"] for s in stages)  # noqa: E731
    return {
        "workspace_id": str(ws_id),
        "n_deals": sum(v["count"] for v in by_stage.values()),
        "n_open": count(OPEN_STAGES),
        "n_closed": count(CLOSED_STAGES),
        "n_won": by_stage[DealStage.CLOSED_WON.value]["count"],
        "n_lost": by_stage[DealStage.CLOSED_LOST.value]["count"],
        "by_stage": by_stage,
        "total_amount_eur": sum(v["amount_eur"] for v in by_stage.values()),
    }


def run_scan(
    session: Session,
    ws_id: uuid.UUID,
    cfg: GateConfig | None = None,
    viewer: Viewer | None = None,
) -> ScanReport:
    """Scan the workspace and record a Run(kind=stats_scan) whose `result` is the report JSON."""
    cfg = cfg or gate_config_from_settings(get_settings())
    started = datetime.now(UTC)
    run = runs.start_run(
        session,
        kind=RunKind.STATS_SCAN,
        workspace_id=ws_id,
        params={"gates": cfg.model_dump(mode="json"), "scope": visibility.scope_key(viewer)},
    )
    try:
        report = scan(
            load_deal_rows(session, ws_id, viewer), cfg, workspace_id=ws_id, created_at=started
        )
    except Exception as exc:
        runs.finish_run(session, run, RunStatus.FAILED, error=f"{type(exc).__name__}: {exc}")
        raise
    runs.finish_run(session, run, RunStatus.SUCCEEDED, result=report)
    return report
