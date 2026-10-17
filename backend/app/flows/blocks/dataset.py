"""dataset: read a CRM table, an uploaded file or a PostgreSQL table through the loader."""

from __future__ import annotations

import pandas as pd

from app.flows.blocks._common import BlockError, BlockOutput, Ctx
from app.flows.schemas import DatasetConfig


def run(cfg: DatasetConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    max_rows = ctx.limits.max_rows
    df = ctx.loader.load(cfg.dataset, max_rows)  # SourceError propagates with its clean message
    warnings: list[str] = []
    if df.attrs.get("capped"):
        warnings.append(f"rows capped at {max_rows}")
    if len(df) > max_rows:
        df = df.head(max_rows)
        if not warnings:
            warnings.append(f"rows capped at {max_rows}")
    df = df.copy()
    df.columns = [str(c) for c in df.columns]
    if df.columns.duplicated().any():
        raise BlockError("the dataset has duplicate column names")
    df.attrs = {}
    return BlockOutput(frames={"out": df.reset_index(drop=True)}, warnings=warnings)
