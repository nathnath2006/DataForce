"""sort: stable multi-key sort (nulls last), then an optional limit."""

from __future__ import annotations

import pandas as pd

from app.flows.blocks._common import BlockOutput, Ctx, require
from app.flows.schemas import SortConfig


def run(cfg: SortConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"]
    require(df, [k.column for k in cfg.keys], "sort column")
    out = df.sort_values(
        [k.column for k in cfg.keys],
        ascending=[not k.descending for k in cfg.keys],
        kind="stable",
        na_position="last",
    )
    if cfg.limit is not None:
        out = out.head(cfg.limit)
    return BlockOutput(frames={"out": out.reset_index(drop=True)})
