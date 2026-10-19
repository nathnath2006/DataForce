"""Pure query engine: filters and exact pandas aggregates over a frame. Column names are checked
against the frame; no expression is ever evaluated."""

from __future__ import annotations

import pandas as pd

from app.api.schemas_viz import Filter, Measure, QueryRequest
from app.flows.blocks._common import dtype_of, is_numeric_kind, jsonable
from app.services.errors import InvalidInputError

NUMERIC_ONLY = ("sum", "mean", "median")


def check_columns(df: pd.DataFrame, names: list[str]) -> None:
    have = {str(c) for c in df.columns}
    for n in names:
        if n not in have:
            raise InvalidInputError(f"column '{n}' does not exist in this source")


def _coerce(s: pd.Series, v):
    kind = dtype_of(s)
    try:
        if is_numeric_kind(kind):
            return float(v)
        if kind in ("date", "datetime"):
            return pd.Timestamp(v)
        if kind == "boolean":
            if isinstance(v, str):
                return v.strip().lower() in ("true", "1", "yes")
            return bool(v)
    except (TypeError, ValueError):
        raise InvalidInputError(f"cannot compare column '{s.name}' ({kind}) with {v!r}") from None
    return str(v) if v is not None else v


def filter_mask(df: pd.DataFrame, f: Filter) -> pd.Series:
    s = df[f.column]
    if f.op == "is_null":
        return s.isna()
    if f.op == "not_null":
        return s.notna()
    if f.op == "contains":
        if f.value is None:
            raise InvalidInputError("contains needs a value")
        return s.astype("string").str.contains(str(f.value), case=False, regex=False).fillna(False)
    if f.op == "in":
        vals = f.value if isinstance(f.value, list) else [f.value]
        if len(vals) > 500:
            raise InvalidInputError("too many values in a filter")
        m = pd.Series(False, index=df.index)
        for v in vals:
            m |= _eq(s, v)
        return m
    if f.op == "eq":
        return _eq(s, f.value)
    if f.op == "ne":
        return s.notna() & ~_eq(s, f.value)
    if isinstance(f.value, list):
        raise InvalidInputError("a list only works with 'in'")
    v = _coerce(s, f.value)
    ok = s.notna()
    cmp = {"lt": s < v, "le": s <= v, "gt": s > v, "ge": s >= v}[f.op]
    return (cmp & ok).fillna(False).astype(bool)


def _eq(s: pd.Series, v) -> pd.Series:
    if v is None:
        return s.isna()
    c = _coerce(s, v)
    return (s.notna() & (s == c)).fillna(False).astype(bool)


def apply_filters(df: pd.DataFrame, filters: list[Filter]) -> pd.DataFrame:
    check_columns(df, [f.column for f in filters])
    for f in filters:
        df = df[filter_mask(df, f)]
    return df


def measure_name(m: Measure) -> str:
    return "count" if m.column == "*" else f"{m.agg}({m.column})"


def _aggregate(df: pd.DataFrame, dims: list[str], measures: list[Measure]) -> pd.DataFrame:
    data = pd.DataFrame(index=df.index)
    for d in dims:
        data[d] = df[d]
    names: list[str] = []
    for m in measures:
        name = measure_name(m)
        if name in names or name in dims:
            continue
        names.append(name)
        if m.column == "*":
            data[name] = 1
            continue
        col = df[m.column]
        kind = dtype_of(col)
        if m.agg in NUMERIC_ONLY and not (is_numeric_kind(kind) or kind == "boolean"):
            raise InvalidInputError(f"{m.agg} needs a numeric column; '{m.column}' is {kind}")
        data[name] = col.astype("float64") if kind == "boolean" else col
    if not dims:
        row = {}
        for m in measures:
            name = measure_name(m)
            if name in row:
                continue
            row[name] = _reduce(data[name], m.agg)
        return pd.DataFrame([row])
    g = data.groupby(dims, dropna=False, sort=False)
    parts: dict[str, pd.Series] = {}
    for m in measures:
        name = measure_name(m)
        if name in parts:
            continue
        if m.agg == "count":
            parts[name] = g.size() if m.column == "*" else g[name].count()
        elif m.agg == "count_distinct":
            parts[name] = g[name].nunique()
        else:
            parts[name] = g[name].agg(m.agg)
    if not parts:
        return g.size().reset_index().drop(columns=0)
    return pd.DataFrame(parts).reset_index()


def _reduce(s: pd.Series, agg: str):
    if agg == "count":
        return int(len(s)) if s.name == "count" else int(s.count())
    if agg == "count_distinct":
        return int(s.nunique())
    if len(s.dropna()) == 0:
        return None
    return getattr(s, agg)()


def run(df: pd.DataFrame, req: QueryRequest) -> tuple[pd.DataFrame, int, int, list[str]]:
    """Returns (result frame, n filtered rows, n groups before the limit, notes)."""
    dims = list(dict.fromkeys(req.dimensions))
    check_columns(df, dims + [m.column for m in req.measures if m.column != "*"])
    notes: list[str] = []
    kept = apply_filters(df, req.filters)
    out = _aggregate(kept, dims, req.measures)
    n_groups = len(out)
    sort = req.sort
    cols = [str(c) for c in out.columns]
    for k in sort:
        if k.by not in cols:
            raise InvalidInputError(f"cannot sort by '{k.by}': it is not an output column")
    if sort and dims:
        out = _sort(out, [k.by for k in sort], [not k.descending for k in sort])
    elif dims:
        measure_cols = [c for c in cols if c not in dims]
        first = dims[0]
        if measure_cols and dtype_of(out[first]) not in ("date", "datetime"):
            out = _sort(out, [measure_cols[0], *dims], [False] + [True] * len(dims))
        else:
            out = _sort(out, [first], [True])
    if n_groups > req.limit:
        notes.append(f"showing the first {req.limit} of {n_groups} groups")
        out = out.head(req.limit)
    return out.reset_index(drop=True), len(kept), n_groups, notes


def _sort(df: pd.DataFrame, by: list[str], asc: list[bool]) -> pd.DataFrame:
    return df.sort_values(by, ascending=asc, na_position="last", kind="mergesort")


def to_rows(df: pd.DataFrame) -> tuple[list[dict], list[list]]:
    kinds = [dtype_of(df.iloc[:, i]) for i in range(df.shape[1])]
    cols = [{"name": str(c), "dtype": k} for c, k in zip(df.columns, kinds, strict=True)]
    rows = [
        [jsonable(v, k == "date") for v, k in zip(r, kinds, strict=True)]
        for r in df.itertuples(index=False)
    ]
    return cols, rows
