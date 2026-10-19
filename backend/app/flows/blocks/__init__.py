"""One module per block; REGISTRY maps a config `type` to its run function."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd

from app.flows.blocks import (
    aging,
    chart,
    cluster,
    columns,
    dataset,
    dedup,
    domain,
    filter,
    forecast,
    group,
    join,
    model,
    pivot,
    sort,
    split,
    stats,
    window,
)
from app.flows.blocks._common import BlockError, BlockOutput, Ctx

REGISTRY: dict[str, Callable[[Any, dict[str, pd.DataFrame], Ctx], BlockOutput]] = {
    "dataset": dataset.run,
    "filter": filter.run,
    "sort": sort.run,
    "columns": columns.run,
    "group": group.run,
    "join": join.run,
    "pivot": pivot.run,
    "stats": stats.run,
    "chart": chart.run,
    "split": split.run,
    "model": model.run,
    "cluster": cluster.run,
    "dedup": dedup.run,
    "aging": aging.run,
    "forecast": forecast.run,
    "window": window.run,
    "domain": domain.run,
}
__all__ = ["REGISTRY", "BlockError", "BlockOutput", "Ctx"]
