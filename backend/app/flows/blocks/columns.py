"""columns: keep (in order), rename, then computed columns (structured ops, no expressions)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.flows.blocks._common import BlockError, BlockOutput, Ctx, require, to_float
from app.flows.schemas import ColumnsConfig, Computed, Operand


def _num(df: pd.DataFrame, o: Operand) -> pd.Series:
    if o.column is not None:
        require(df, [o.column])
        return to_float(df[o.column], o.column)
    return pd.Series(float(o.value or 0.0), index=df.index)


def _compute(df: pd.DataFrame, c: Computed) -> pd.Series:
    if c.op == "bucket":
        if c.left.column is None or not c.edges or not c.labels:
            raise BlockError(f"'{c.name}': bucket needs a column, edges and labels")
        if len(c.labels) != len(c.edges) + 1:
            raise BlockError(f"'{c.name}': labels must be one more than edges")
        if any(b <= a for a, b in zip(c.edges, c.edges[1:], strict=False)):
            raise BlockError(f"'{c.name}': edges must be strictly ascending")
        x = _num(df, c.left)
        bins = [-np.inf, *c.edges, np.inf]
        cut = pd.cut(x, bins=bins, labels=c.labels, right=False, ordered=False)
        return cut.astype(object).where(cut.notna(), None)
    if c.right is None:
        raise BlockError(f"'{c.name}': {c.op} needs a right operand")
    if c.op == "days_between":
        if c.left.column is None or c.right.column is None:
            raise BlockError(f"'{c.name}': days_between needs two date columns")
        require(df, [c.left.column, c.right.column])
        try:
            a = pd.to_datetime(df[c.left.column])
            b = pd.to_datetime(df[c.right.column])
            return (b - a).dt.total_seconds() / 86400
        except (ValueError, TypeError) as e:
            raise BlockError(f"'{c.name}': both columns must be dates") from e
    a, b = _num(df, c.left), _num(df, c.right)
    if c.op == "add":
        r = a + b
    elif c.op == "sub":
        r = a - b
    elif c.op == "mul":
        r = a * b
    else:
        r = a / b.where(b != 0)
    return r.where(np.isfinite(r))


def run(cfg: ColumnsConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"]
    if cfg.keep is not None:
        require(df, cfg.keep)
        df = df[list(cfg.keep)]
    if cfg.rename:
        require(df, list(cfg.rename))
        df = df.rename(columns=cfg.rename)
        if df.columns.duplicated().any():
            raise BlockError("renaming produces duplicate column names")
    df = df.copy()
    for c in cfg.computed:
        df[c.name] = _compute(df, c)
    return BlockOutput(frames={"out": df.reset_index(drop=True)})
