"""Explain: each group of each attribute against the rest, through the existing stats block
(same gates, same Wilson / Newcombe / Fisher or bootstrap / Mann-Whitney, same BH). Nothing is
reimplemented here; one BH is applied across every comparison of the whole run."""

from __future__ import annotations

import time

import pandas as pd

from app.api.schemas_viz import ExplainFinding, ExplainRequest
from app.domain.schemas import GateConfig
from app.flows.blocks import stats as stats_block
from app.flows.blocks._common import BlockError, Ctx
from app.flows.ports import FlowLimits
from app.flows.schemas import StatsConfig, StatsView
from app.stats.significance import benjamini_hochberg
from app.viz.engine import check_columns
from app.viz.source import TIME_BUDGET_S


def explain(
    df: pd.DataFrame, req: ExplainRequest, gates: GateConfig, limits: FlowLimits
) -> tuple[list[ExplainFinding], str, list[str]]:
    attrs = list(dict.fromkeys(req.attributes))
    check_columns(df, [req.measure.column, *attrs])
    ctx = Ctx(
        gates=gates,
        limits=limits,
        loader=None,
        deadline=time.monotonic() + TIME_BUDGET_S,  # type: ignore[arg-type]
    )
    findings: list[ExplainFinding] = []
    prepared: list[tuple[str, stats_block.Prepared]] = []
    notes: list[str] = []
    method = ""
    for a in attrs:
        if a == req.measure.column:
            notes.append(f"'{a}' is the measure itself and was skipped as an attribute")
            continue
        cfg = StatsConfig(
            group_by=a,
            outcome=req.measure.column,
            outcome_kind=req.measure.kind,
            success_value=req.measure.success_value,
        )
        try:
            prep = stats_block.prepare(cfg, {"in": df}, ctx)
        except BlockError as exc:
            notes.append(f"'{a}': {exc}")
            continue
        prepared.append((a, prep))
    pooled = benjamini_hochberg([p for _, pr in prepared for p in pr.pvalues])
    pos = 0
    for a, prep in prepared:
        out = prep.finish(pooled[pos : pos + len(prep.pvalues)])
        pos += len(prep.pvalues)
        view = out.view
        assert isinstance(view, StatsView)
        method = view.method
        notes.extend(f"'{a}': {w}" for w in out.warnings)
        for r in view.rows:
            direction = "none" if not r.diff else ("higher" if r.diff > 0 else "lower")
            findings.append(
                ExplainFinding(
                    attribute=a,
                    group=r.group,
                    n=r.n,
                    value=r.value,
                    rest_value=r.rest_value,
                    diff=r.diff,
                    diff_ci_low=r.diff_ci_low,
                    diff_ci_high=r.diff_ci_high,
                    p_value=r.p_value,
                    q_value=r.q_value,
                    direction=direction,  # type: ignore[arg-type]
                    status=r.status,
                    reasons=r.reasons,
                )
            )
    return findings, method, notes


def split_sorted(
    findings: list[ExplainFinding],
) -> tuple[list[ExplainFinding], list[ExplainFinding]]:
    ver = [f for f in findings if f.status == "verified"]
    not_ver = [f for f in findings if f.status != "verified"]
    ver.sort(key=lambda f: (f.q_value if f.q_value is not None else 1.0, -abs(f.diff or 0.0)))
    not_ver.sort(key=lambda f: -f.n)
    return ver, not_ver
