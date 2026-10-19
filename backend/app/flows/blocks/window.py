"""window: lag, lead, rolling mean / sum / count, rank, row_number and pct_change over a
partition ordered by one column.

Nulls: rows with a null order value sort last; rolling functions skip null values; lag, lead and
pct_change propagate them (pct_change is null when the earlier value is 0). rank and row_number
use the order column only; ties share the lowest rank, row_number keeps the input order.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.flows.blocks._common import BlockError, BlockOutput, Ctx, require, to_float
from app.flows.schemas import WindowConfig

NEEDS_VALUE = ("lag", "lead", "rolling_mean", "rolling_sum", "rolling_count", "pct_change")


def _period_frame(df: pd.DataFrame, cfg: WindowConfig, warnings: list[str]) -> pd.DataFrame:
    assert cfg.column is not None
    try:
        d = pd.to_datetime(df[cfg.order_by])
    except (ValueError, TypeError) as e:
        raise BlockError(f"column '{cfg.order_by}' is not a date") from e
    if cfg.period == "month":
        label = d.dt.strftime("%Y-%m")
    elif cfg.period == "year":
        label = d.dt.strftime("%Y")
    else:
        label = (
            d.dt.year.astype("Int64").astype(str) + "-Q" + d.dt.quarter.astype("Int64").astype(str)
        )
    label = label.where(d.notna())
    agg = pd.DataFrame({c: df[c] for c in cfg.partition_by})
    agg["period"] = label
    agg[cfg.column] = to_float(df[cfg.column], cfg.column)
    skipped = int(label.isna().sum())
    if skipped:
        warnings.append(f"{skipped} rows without a date skipped")
    return (
        agg.dropna(subset=["period"])
        .groupby([*cfg.partition_by, "period"], dropna=False, sort=True)[cfg.column]
        .sum(min_count=1)
        .reset_index()
    )


def run(cfg: WindowConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"].reset_index(drop=True)
    require(df, [cfg.order_by, *cfg.partition_by, *([cfg.column] if cfg.column else [])])
    if cfg.fn in NEEDS_VALUE and cfg.column is None:
        raise BlockError(f"{cfg.fn} needs a value column")
    if cfg.alias in df.columns:
        raise BlockError(f"the input already has a column named '{cfg.alias}'")
    warnings: list[str] = []
    order_col = cfg.order_by
    if cfg.period is not None:
        if cfg.column is None:
            raise BlockError("a period needs a value column to sum")
        df = _period_frame(df, cfg, warnings)
        order_col = "period"
    parts = list(cfg.partition_by)
    srt = df.assign(_o=df[order_col]).sort_values(
        by=[*parts, "_o"],
        ascending=[True] * len(parts) + [not cfg.descending],
        kind="stable",
        na_position="last",
    )
    gid = (
        srt.groupby(parts, dropna=False, sort=False).ngroup()
        if parts
        else pd.Series(0, index=srt.index)
    )
    if cfg.fn == "row_number":
        res = gid.groupby(gid).cumcount() + 1
    elif cfg.fn == "rank":
        res = (
            srt["_o"]
            .groupby(gid)
            .rank(method="min", ascending=not cfg.descending, na_option="keep")
        )
    else:
        assert cfg.column is not None
        values = to_float(srt[cfg.column], cfg.column)
        vg = values.groupby(gid)
        if cfg.fn == "lag":
            res = vg.shift(cfg.k)
        elif cfg.fn == "lead":
            res = vg.shift(-cfg.k)
        elif cfg.fn == "pct_change":
            prev = vg.shift(cfg.k)
            with np.errstate(divide="ignore", invalid="ignore"):
                ch = (values - prev) / prev
            res = ch.where(np.isfinite(ch))
        else:
            roll = vg.rolling(cfg.k, min_periods=1)
            fn = {"rolling_mean": roll.mean, "rolling_sum": roll.sum, "rolling_count": roll.count}
            res = fn[cfg.fn]().reset_index(level=0, drop=True)
    out = df.copy()
    out[cfg.alias] = res.astype("float64").reindex(df.index)
    return BlockOutput(frames={"out": out}, warnings=warnings)
