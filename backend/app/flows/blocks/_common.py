"""Shared helpers for flow blocks: errors, the run context, dtype mapping, JSON-safe values."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from app.domain.schemas import GateConfig
from app.flows.ports import FlowLimits, SourceLoader


class BlockError(Exception):
    """A user-facing problem with a block's settings or input. The message is shown as is."""


@dataclass
class Ctx:
    gates: GateConfig
    limits: FlowLimits
    loader: SourceLoader
    deadline: float | None = None  # time.monotonic() value after which blocks must stop
    rows_multiplied: bool = False  # an upstream join produced more rows than its left input
    split_verified: bool = False  # model only: train/test come from the same split block

    def check(self) -> None:
        """Cooperative cancellation: long loops call this and stop with a clean error."""
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise BlockError("time limit reached; filter or sample the data first")


@dataclass
class BlockOutput:
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)  # by output port
    view: Any = None
    warnings: list[str] = field(default_factory=list)
    n_rows: int | None = None  # only for blocks with no output table (chart)
    rows_multiplied: bool = False  # set by a join whose output has more rows than its left input


def dtype_of(s: pd.Series) -> str:
    """Map a pandas column to ColumnInfo.dtype: number, integer, text, boolean, date, datetime,
    other. Object columns are classified by their non-null contents."""
    t = s.dtype
    if pd.api.types.is_bool_dtype(t):
        return "boolean"
    if pd.api.types.is_integer_dtype(t):
        return "integer"
    if pd.api.types.is_float_dtype(t):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(t):
        nn = s.dropna()
        if len(nn) and (nn == nn.dt.normalize()).all():
            return "date"
        return "datetime" if len(nn) else "date"
    if isinstance(t, pd.CategoricalDtype):
        return "text"
    if t is np.dtype("O"):
        kind = pd.api.types.infer_dtype(s, skipna=True)
        return {
            "string": "text",
            "empty": "text",
            "boolean": "boolean",
            "integer": "integer",
            "floating": "number",
            "mixed-integer-float": "number",
            "decimal": "number",
            "date": "date",
            "datetime": "datetime",
            "datetime64": "datetime",
        }.get(kind, "other")
    if pd.api.types.is_string_dtype(t):
        return "text"
    return "other"


def is_numeric_kind(kind: str) -> bool:
    return kind in ("number", "integer")


def jsonable(v: Any, date_only: bool = False) -> Any:
    """A JSON-safe Python value: NaN/inf/NaT/NA become None, numpy types plain, dates ISO."""
    if v is None or v is pd.NaT or v is pd.NA:
        return None
    if isinstance(v, bool | np.bool_):
        return bool(v)
    if isinstance(v, int | np.integer):
        return int(v)
    if isinstance(v, float | np.floating | Decimal):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat() if date_only else v.isoformat()
    if isinstance(v, datetime):
        return v.date().isoformat() if date_only else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str):
        return v
    if isinstance(v, list | tuple):
        return [jsonable(x) for x in v]
    return str(v)


def fnum(x: Any) -> float | None:
    """A finite float or None."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def require(df: pd.DataFrame, cols: list[str], what: str = "column") -> None:
    for c in cols:
        if c not in df.columns:
            raise BlockError(f"{what} '{c}' does not exist in the input")


def to_float(s: pd.Series, name: str) -> pd.Series:
    """A numeric column as float64 (inf becomes NaN); a clear error otherwise."""
    kind = dtype_of(s)
    if not is_numeric_kind(kind):
        raise BlockError(f"column '{name}' is not numeric ({kind})")
    out = pd.to_numeric(s, errors="coerce").astype("float64")
    return out.where(np.isfinite(out))


def matches(s: pd.Series, value: Any) -> pd.Series:
    """Boolean mask of s == value (nulls never match); strings compare case-sensitively."""
    nn = s.notna()
    out = pd.Series(False, index=s.index)
    if value is None:
        return out
    obj = s[nn].astype(object)
    out[nn] = (obj == value).to_numpy(dtype=bool)
    return out


def cap_rows(df: pd.DataFrame, max_rows: int, warnings: list[str]) -> pd.DataFrame:
    if len(df) > max_rows:
        warnings.append(f"rows capped at {max_rows}")
        return df.head(max_rows)
    return df
