"""filter: boolean masks only. Nulls never match a comparison (only is_null matches them)."""

from __future__ import annotations

import operator
from typing import Any

import pandas as pd

from app.flows.blocks._common import BlockError, BlockOutput, Ctx, dtype_of, require
from app.flows.schemas import Condition, FilterConfig

_CMP = {
    "eq": operator.eq,
    "ne": operator.ne,
    "lt": operator.lt,
    "le": operator.le,
    "gt": operator.gt,
    "ge": operator.ge,
}


def _is_num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _coerce(kind: str, v: Any, col: str) -> Any:
    bad = BlockError(f"cannot compare column '{col}' ({kind}) with {v!r}")
    if kind in ("number", "integer"):
        if not _is_num(v):
            raise bad
    elif kind in ("date", "datetime"):
        if not isinstance(v, str):
            raise bad
        try:
            return pd.Timestamp(v)
        except (ValueError, TypeError) as e:
            raise bad from e
    elif kind == "text":
        if not isinstance(v, str):
            raise bad
    elif kind == "boolean":
        if not isinstance(v, bool):
            raise bad
    return v


def _mask(df: pd.DataFrame, c: Condition) -> pd.Series:
    require(df, [c.column])
    s = df[c.column]
    nn = s.notna()
    if c.op == "is_null":
        return ~nn
    if c.op == "not_null":
        return nn
    kind = dtype_of(s)
    out = pd.Series(False, index=df.index)
    sub = s[nn]
    if kind in ("date", "datetime"):
        try:
            sub = pd.to_datetime(sub)
        except (ValueError, TypeError) as e:
            raise BlockError(f"column '{c.column}' is not a valid date column") from e
    try:
        if c.op in ("contains", "not_contains"):
            if kind != "text" or not isinstance(c.value, str):
                raise BlockError(f"'{c.op}' needs a text column and a text value")
            hit = sub.astype(str).str.contains(c.value, case=False, regex=False)
            out[nn] = hit.to_numpy(bool) if c.op == "contains" else (~hit).to_numpy(bool)
        elif c.op == "in":
            if not isinstance(c.value, list):
                raise BlockError(f"'in' needs a list of values for column '{c.column}'")
            vals = [_coerce(kind, v, c.column) for v in c.value if v is not None]
            out[nn] = sub.isin(vals).to_numpy(bool)
        else:
            if c.value is None or isinstance(c.value, list):
                raise BlockError(f"'{c.op}' needs a single value for column '{c.column}'")
            if kind == "boolean" and c.op not in ("eq", "ne"):
                raise BlockError(f"cannot order boolean column '{c.column}'")
            v = _coerce(kind, c.value, c.column)
            out[nn] = _CMP[c.op](sub.astype(object) if kind == "boolean" else sub, v).to_numpy(bool)
    except TypeError as e:
        raise BlockError(f"cannot compare column '{c.column}' ({kind}) with {c.value!r}") from e
    return out


def run(cfg: FilterConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"]
    if not cfg.conditions:
        return BlockOutput(frames={"out": df})
    masks = [_mask(df, c) for c in cfg.conditions]
    m = masks[0]
    for x in masks[1:]:
        m = (m & x) if cfg.mode == "all" else (m | x)
    return BlockOutput(frames={"out": df[m].reset_index(drop=True)})
