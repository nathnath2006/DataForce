"""Explain applies one BH across all attributes of a run (methods review #9)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.api.schemas_viz import ExplainMeasure, ExplainRequest
from app.domain.schemas import GateConfig
from app.flows.blocks import stats as stats_block
from app.flows.blocks._common import Ctx
from app.flows.ports import FlowLimits
from app.flows.schemas import StatsConfig
from app.viz.explain import explain

GATES = GateConfig(bootstrap_resamples=200)


def _null_frame(rng, n=1500, n_attr=5):
    df = pd.DataFrame({f"a{i}": rng.integers(0, 8, n).astype(str) for i in range(n_attr)})
    df["won"] = rng.random(n) < 0.30
    return df


def test_pooled_bh_cuts_false_verified_runs():
    rng = np.random.default_rng(11)
    runs, per_attr_runs, pooled_runs = 120, 0, 0
    for _ in range(runs):
        df = _null_frame(rng)
        attrs = [c for c in df.columns if c != "won"]
        req = ExplainRequest.model_construct(
            attributes=attrs,
            measure=ExplainMeasure(column="won", kind="rate", success_value=True),
            filters=[],
        )
        findings, _, _ = explain(df, req, GATES, FlowLimits())
        pooled_runs += any(f.status == "verified" for f in findings)
        ctx = Ctx(gates=GATES, limits=FlowLimits(), loader=None, deadline=None)  # type: ignore[arg-type]
        for a in attrs:
            cfg = StatsConfig(group_by=a, outcome="won", outcome_kind="rate", success_value=True)
            out = stats_block.run(cfg, {"in": df}, ctx)
            if any(r.status == "verified" for r in out.view.rows):
                per_attr_runs += 1
                break
    assert per_attr_runs >= 8  # per-attribute BH: roughly a third of null runs
    assert pooled_runs <= 0.10 * runs
    assert pooled_runs < per_attr_runs
