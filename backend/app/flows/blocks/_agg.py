"""Grouped aggregation shared by the group and pivot blocks."""

from __future__ import annotations

import pandas as pd

from app.flows.blocks._common import BlockError, dtype_of, require, to_float

Spec = tuple[str | None, str, str]  # (column, fn, alias)


def aggregate_by(df: pd.DataFrame, by: list[str], specs: list[Spec]) -> pd.DataFrame:
    """One row per distinct `by` key (null keys kept, keys sorted); `by=[]` gives one row."""
    require(df, by, "group column")
    aliases = [a for _, _, a in specs]
    if len(set(aliases)) != len(aliases):
        raise BlockError("aggregation names must be unique")
    clash = set(aliases) & set(by)
    if clash:
        raise BlockError(f"aggregation name '{sorted(clash)[0]}' clashes with a group column")
    keys = list(by)
    work = df[keys].copy() if keys else pd.DataFrame(index=df.index)
    if not keys:
        work["__all__"] = 0
        keys = ["__all__"]
    cols: list[str] = []
    for i, (column, fn, _) in enumerate(specs):
        name = f"__a{i}"
        cols.append(name)
        if column is None:
            if fn != "count":
                raise BlockError(f"'{fn}' needs a column")
            work[name] = 1
            continue
        require(df, [column])
        if fn in ("sum", "mean", "median"):
            work[name] = to_float(df[column], column)
        else:
            if fn in ("min", "max") and dtype_of(df[column]) == "other":
                raise BlockError(f"'{fn}' cannot be applied to column '{column}'")
            work[name] = df[column]
    g = work.groupby(keys, dropna=False, sort=True)
    parts: list[pd.Series] = []
    for name, (column, fn, alias) in zip(cols, specs, strict=True):
        if fn == "count":
            s = g.size() if column is None else g[name].count()
        elif fn == "count_distinct":
            s = g[name].nunique()
        elif fn == "sum":
            s = g[name].sum(min_count=1)
        elif fn == "mean":
            s = g[name].mean()
        elif fn == "median":
            s = g[name].median()
        elif fn == "min":
            s = g[name].min()
        elif fn == "max":
            s = g[name].max()
        else:
            raise BlockError(f"unknown aggregation '{fn}'")
        parts.append(s.rename(alias))
    out = pd.concat(parts, axis=1).reset_index()
    if by:
        return out
    return out.drop(columns=["__all__"])
