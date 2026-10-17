"""Shared helpers: turn rows from any source into a clean DataFrame, and describe its columns."""

from __future__ import annotations

import datetime as dt
import decimal
import json
import uuid
from typing import Any

import pandas as pd

from app.flows.schemas import ColumnInfo


def dtype_of(series: pd.Series) -> str:
    kind = series.dtype
    if pd.api.types.is_bool_dtype(kind):
        return "boolean"
    if pd.api.types.is_integer_dtype(kind):
        return "integer"
    if pd.api.types.is_float_dtype(kind):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(kind):
        return "date" if _all_midnight(series) else "datetime"
    if pd.api.types.is_string_dtype(kind):
        return "text"
    if pd.api.types.is_object_dtype(kind):
        sample = series.dropna()
        if len(sample) and all(isinstance(v, bool) for v in sample.head(50)):
            return "boolean"
        if len(sample) and all(isinstance(v, str) for v in sample.head(50)):
            return "text"
    return "other"


def _all_midnight(series: pd.Series) -> bool:
    values = series.dropna()
    return bool(len(values) == 0 or (values == values.dt.normalize()).all())


def column_infos(df: pd.DataFrame) -> list[dict[str, str]]:
    return [ColumnInfo(name=str(c), dtype=dtype_of(df[c])).model_dump() for c in df.columns]  # type: ignore[arg-type]


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Decimal -> float, dates -> datetime64, UUID -> str, JSON values -> str, so the engine
    only meets pandas-native dtypes."""
    for name in df.columns:
        col = df[name]
        if not pd.api.types.is_object_dtype(col.dtype):
            continue
        sample = next((v for v in col if v is not None and v is not pd.NA and v == v), None)
        if sample is None:
            continue
        if isinstance(sample, decimal.Decimal):
            df[name] = pd.to_numeric(col.map(lambda v: None if v is None else float(v)))
        elif isinstance(sample, dt.datetime | dt.date):
            df[name] = pd.to_datetime(col, utc=True, errors="coerce").dt.tz_localize(None)
        elif isinstance(sample, uuid.UUID):
            df[name] = col.map(lambda v: None if v is None else str(v))
        elif isinstance(sample, dict | list):
            df[name] = col.map(lambda v: None if v is None else json.dumps(v, default=str))
    return df


def frame_from_rows(rows: list[Any], columns: list[str]) -> pd.DataFrame:
    return normalize_frame(pd.DataFrame.from_records(rows, columns=columns))
