"""pivot: rows x distinct values of `columns`; cells = fn(values).

Flat table layout: the row dimensions, then one column per kept pivot value (labels are the
stringified values, "(missing)" for nulls), then "Total" (when totals and `columns` is set).
With totals, the last row has "Total" as its first key (other keys "") and totals computed on
all rows (not only the kept columns). Without `columns` there is a single value column.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.flows.blocks._agg import aggregate_by
from app.flows.blocks._common import BlockError, BlockOutput, Ctx, jsonable, require
from app.flows.schemas import PivotConfig, PivotView

_ZERO_FNS = ("count", "count_distinct", "sum")
MISSING = "(missing)"


def _norm(v: Any) -> Any:
    return None if (v is None or (not isinstance(v, str) and pd.isna(v))) else v


def _unique(label: str, used: set[str]) -> str:
    out, i = label, 2
    while out in used:
        out, i = f"{label} ({i})", i + 1
    used.add(out)
    return out


def run(cfg: PivotConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"]
    rows = list(cfg.rows)
    require(df, rows, "row column")
    if cfg.values is None and cfg.fn != "count":
        raise BlockError(f"'{cfg.fn}' needs a values column")
    if cfg.values is not None:
        require(df, [cfg.values], "values column")
    if cfg.columns is not None:
        require(df, [cfg.columns], "pivot column")
    spec = [(cfg.values, cfg.fn, "__v")]
    empty = 0 if cfg.fn in _ZERO_FNS else None
    warnings: list[str] = []

    row_tot = aggregate_by(df, rows, spec)
    keys = [tuple(_norm(v) for v in r) for r in row_tot[rows].itertuples(index=False)]
    row_total_vals = row_tot["__v"].tolist()
    grand = aggregate_by(df, [], spec)["__v"].iloc[0]

    truncated = 0
    if cfg.columns is None:
        label = cfg.fn if cfg.values is None else f"{cfg.fn}({cfg.values})"
        labels = [label]
        cells = [[v] for v in row_total_vals]
        col_total: list[Any] = []
        has_total_col = False
    else:
        raw = df[cfg.columns]
        lab = (
            raw.astype(object)
            .where(raw.notna(), None)
            .map(lambda v: MISSING if v is None else str(v))
        )
        counts = lab.value_counts()
        order = sorted(counts.index, key=lambda x: (-int(counts[x]), x))
        keep = order[: cfg.max_columns]
        truncated = len(order) - len(keep)
        if truncated:
            warnings.append(
                f"{truncated} pivot column values dropped (max_columns = {cfg.max_columns})"
            )
        first: dict[str, Any] = {}
        for x, lb in zip(raw.tolist(), lab.tolist(), strict=True):
            first.setdefault(lb, x)
        present = [k for k in keep if k != MISSING]
        try:
            present.sort(key=lambda k: first[k])
        except TypeError:
            present.sort()
        labels = present + ([MISSING] if MISSING in keep else [])
        work = df[rows].copy()
        work["__pc__"] = lab
        if cfg.values is not None:
            work[cfg.values] = df[cfg.values]
        agg = aggregate_by(work[work["__pc__"].isin(labels)], [*rows, "__pc__"], spec)
        lookup: dict[tuple[Any, ...], Any] = {}
        for r in agg.itertuples(index=False):
            vals = list(r)
            lookup[(tuple(_norm(v) for v in vals[: len(rows)]), vals[len(rows)])] = vals[-1]
        cells = [[lookup.get((k, lb), empty) for lb in labels] for k in keys]
        has_total_col = cfg.totals
        col_total = []
        if cfg.totals:
            ct = aggregate_by(work[work["__pc__"].isin(labels)].assign(), ["__pc__"], spec)
            ctd = dict(zip(ct["__pc__"], ct["__v"], strict=True))
            col_total = [ctd.get(lb, empty) for lb in labels]
    used = set(rows)
    out_labels = [_unique(lb, used) for lb in labels]
    total_label = _unique("Total", used) if has_total_col else None

    flat_rows: list[list[Any]] = []
    view_rows: list[dict[str, Any]] = []
    for k, rc, rt in zip(keys, cells, row_total_vals, strict=True):
        cs = rc + ([rt] if has_total_col else [])
        flat_rows.append([*k, *cs])
        view_rows.append({"keys": [jsonable(x) for x in k], "cells": [jsonable(x) for x in cs]})
    if cfg.totals:
        k = ("Total", *([""] * (len(rows) - 1)))
        cs = (
            (col_total + [grand])
            if cfg.columns is not None and has_total_col
            else ([grand] if cfg.columns is None else col_total)
        )
        flat_rows.append([*k, *cs])
        view_rows.append({"keys": list(k), "cells": [jsonable(x) for x in cs]})
    names = [*rows, *out_labels, *([total_label] if total_label else [])]
    table = pd.DataFrame(flat_rows, columns=names)
    view = PivotView(
        row_headers=rows,
        column_values=[*out_labels, *([total_label] if total_label else [])],
        rows=view_rows,
        truncated_columns=truncated,
    )
    return BlockOutput(frames={"out": table}, view=view, warnings=warnings)
