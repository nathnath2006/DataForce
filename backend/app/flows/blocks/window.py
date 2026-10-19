"""window: lag, lead, rolling mean / sum / count, rank, row_number and pct_change over a
partition ordered by one column.

Nulls: rows with a null order value sort last; rolling functions skip null values; lag and lead
propagate them. pct_change is null when the earlier value is missing, 0 or negative, and adds an
absolute-change column. With a period, periods without rows count as 0 in the sums. rank and
row_number use the order column only; ties share the lowest rank, row_number keeps the input order.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.flows.blocks._common import BlockError, BlockOutput, Ctx, require, to_float
from app.flows.schemas import WindowConfig

NEEDS_VALUE = ("lag", "lead", "rolling_mean", "rolling_sum", "rolling_count", "pct_change")


_FREQ = {"month": "M", "quarter": "Q", "year": "Y"}


def _label(p: pd.Period, period: str) -> str:
    if period == "month":
        return p.strftime("%Y-%m")
    if period == "year":
        return p.strftime("%Y")
    return f"{p.year}-Q{p.quarter}"


def _period_frame(df: pd.DataFrame, cfg: WindowConfig, warnings: list[str]) -> pd.DataFrame:
    """Sum of `column` per partition and period. Periods are densified between the first and the
    last period of each partition: a period without rows is 0 for the sum (a gap is not absent)."""
    assert cfg.column is not None and cfg.period is not None
    try:
        d = pd.to_datetime(df[cfg.order_by])
    except (ValueError, TypeError) as e:
        raise BlockError(f"column '{cfg.order_by}' is not a date") from e
    if getattr(d.dt, "tz", None) is not None:
        d = d.dt.tz_localize(None)
    freq = _FREQ[cfg.period]
    agg = pd.DataFrame({c: df[c] for c in cfg.partition_by})
    agg["_p"] = d.dt.to_period(freq)
    agg[cfg.column] = to_float(df[cfg.column], cfg.column)
    skipped = int(agg["_p"].isna().sum())
    if skipped:
        warnings.append(f"{skipped} rows without a date skipped")
    parts = list(cfg.partition_by)
    sums = (
        agg.dropna(subset=["_p"])
        .groupby([*parts, "_p"], dropna=False, sort=True)[cfg.column]
        .sum(min_count=1)
        .reset_index()
    )
    gcols = parts or ["_g"]
    if not parts:
        sums["_g"] = 0
    pieces: list[pd.DataFrame] = []
    added = 0
    for key, grp in sums.groupby(gcols, dropna=False, sort=True):
        full = pd.DataFrame({"_p": pd.period_range(grp["_p"].min(), grp["_p"].max(), freq=freq)})
        m = full.merge(grp[["_p", cfg.column]], on="_p", how="left")
        gap = ~m["_p"].isin(grp["_p"])
        m.loc[gap, cfg.column] = 0.0
        added += int(gap.sum())
        keys = key if isinstance(key, tuple) else (key,)
        for c, v in zip(gcols, keys, strict=True):
            m[c] = v
        pieces.append(m)
    if added:
        warnings.append(f"{added} missing periods were added with a value of 0 (no rows = 0)")
    if not pieces:
        out = pd.DataFrame(columns=[*gcols, "_p", cfg.column])
    else:
        out = pd.concat(pieces, ignore_index=True)
    out["period"] = [_label(x, cfg.period) for x in out["_p"]]
    out = out.drop(columns=["_p", *([] if parts else ["_g"])])
    return out[[*parts, "period", cfg.column]]


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
    abs_change: pd.Series | None = None
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
            # growth needs a positive base: null for a missing, zero or negative previous value
            with np.errstate(divide="ignore", invalid="ignore"):
                ch = (values - prev) / prev
            res = ch.where(np.isfinite(ch) & (prev > 0))
            abs_change = values - prev
            has_row = pd.Series(1.0, index=srt.index).groupby(gid).shift(cfg.k).notna()
            n_null = int((has_row & values.notna() & ~(prev > 0)).sum())
            if n_null:
                warnings.append(
                    f"{n_null} growth values are empty because the previous value is missing, "
                    "zero or negative"
                )
        else:
            roll = vg.rolling(cfg.k, min_periods=1)
            fn = {"rolling_mean": roll.mean, "rolling_sum": roll.sum, "rolling_count": roll.count}
            res = fn[cfg.fn]().reset_index(level=0, drop=True)
    out = df.copy()
    out[cfg.alias] = res.astype("float64").reindex(df.index)
    if abs_change is not None:
        name = f"{cfg.alias}_abs_change"
        if name in out.columns:
            raise BlockError(f"the input already has a column named '{name}'")
        out[name] = abs_change.astype("float64").reindex(df.index)
    return BlockOutput(frames={"out": out}, warnings=warnings)
