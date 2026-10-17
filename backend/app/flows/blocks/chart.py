"""chart: the backend aggregates the points, the browser only draws. No output table."""

from __future__ import annotations

import pandas as pd

from app.flows.blocks._agg import aggregate_by
from app.flows.blocks._common import (
    BlockError,
    BlockOutput,
    Ctx,
    dtype_of,
    fnum,
    jsonable,
    require,
    to_float,
)
from app.flows.schemas import ChartConfig, ChartSeries, ChartView


def run(cfg: ChartConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"]
    require(df, [cfg.x])
    if cfg.series is not None:
        require(df, [cfg.series], "series column")
    if cfg.agg != "count" and cfg.y is None:
        raise BlockError(f"agg '{cfg.agg}' needs a y column")
    if cfg.y is not None:
        require(df, [cfg.y], "y column")
    warnings: list[str] = []
    work = pd.DataFrame({"x": df[cfg.x]})
    if cfg.series is not None:
        work["s"] = (
            df[cfg.series].astype(object).where(df[cfg.series].notna(), "(missing)").astype(str)
        )
    else:
        work["s"] = ""
    if cfg.agg == "none":
        assert cfg.y is not None
        work["y"] = to_float(df[cfg.y], cfg.y)
    elif cfg.agg != "count":
        assert cfg.y is not None
        work["y"] = df[cfg.y]
    dropped = int(work["x"].isna().sum())
    work = work[work["x"].notna()]
    if dropped:
        warnings.append(f"{dropped} rows with a missing x dropped")
    date_only = dtype_of(df[cfg.x]) == "date"
    if cfg.agg == "none":
        pts = work.rename(columns={"y": "v"})
    else:
        spec = [(None if cfg.agg == "count" else "y", cfg.agg, "v")]
        pts = aggregate_by(work, ["s", "x"], spec)
    pts = pts.sort_values(["s", "x"], kind="stable") if len(pts) else pts
    total = len(pts)
    truncated = total > cfg.max_points
    if truncated:
        pts = pts.head(cfg.max_points)
        warnings.append(f"chart truncated to {cfg.max_points} points")
    default_name = cfg.y if cfg.y and cfg.agg != "count" else "count"
    series: list[ChartSeries] = []
    for sname, part in pts.groupby("s", sort=True):
        series.append(
            ChartSeries(
                name=str(sname) or default_name,
                points=[
                    (jsonable(x, date_only), fnum(v))
                    for x, v in zip(part["x"], part["v"], strict=True)
                ],
            )
        )
    y_label = (
        "count" if cfg.agg == "count" else (cfg.y if cfg.agg == "none" else f"{cfg.agg}({cfg.y})")
    )
    view = ChartView(
        chart=cfg.kind, x_label=cfg.x, y_label=str(y_label), series=series, truncated=truncated
    )
    return BlockOutput(view=view, warnings=warnings, n_rows=min(total, cfg.max_points))
