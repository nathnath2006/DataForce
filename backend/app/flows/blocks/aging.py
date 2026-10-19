"""aging: days since a date, relative to the run's start date, and a stagnation flag."""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.flows.blocks._common import BlockError, BlockOutput, Ctx, require
from app.flows.blocks.filter import _mask
from app.flows.schemas import AgingConfig


def run(cfg: AgingConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"]
    require(df, [cfg.column])
    for name in (cfg.alias, "stagnant"):
        if name in df.columns:
            raise BlockError(f"the input already has a column named '{name}'")
    try:
        d = pd.to_datetime(df[cfg.column]).dt.normalize()
    except (ValueError, TypeError) as e:
        raise BlockError(f"column '{cfg.column}' is not a date") from e
    if getattr(d.dt, "tz", None) is not None:
        d = d.dt.tz_localize(None)
    today = pd.Timestamp(ctx.today or date.today())
    days = (today - d).dt.days.astype("float64")
    if cfg.where:
        masks = [_mask(df, c) for c in cfg.where]
        m = masks[0]
        for x in masks[1:]:
            m = (m & x) if cfg.where_mode == "all" else (m | x)
    else:
        m = pd.Series(True, index=df.index)
    out = df.copy()
    out[cfg.alias] = days
    out["stagnant"] = ((days > cfg.stagnant_after_days) & m).to_numpy(dtype=bool)
    warnings = []
    n_null = int(d.isna().sum())
    if n_null:
        warnings.append(f"{n_null} rows have no date: no age, not stagnant")
    return BlockOutput(frames={"out": out}, warnings=warnings)
