"""group: one row per group key; columns = by + aggregation aliases."""

from __future__ import annotations

import pandas as pd

from app.flows.blocks._agg import aggregate_by
from app.flows.blocks._common import BlockOutput, Ctx, cap_rows
from app.flows.schemas import GroupConfig


def run(cfg: GroupConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    specs = [(a.column, a.fn, a.alias) for a in cfg.aggregations]
    out = aggregate_by(inputs["in"], list(cfg.by), specs)
    warnings: list[str] = []
    out = cap_rows(out, ctx.limits.max_rows, warnings)
    return BlockOutput(frames={"out": out.reset_index(drop=True)}, warnings=warnings)
