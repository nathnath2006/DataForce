"""split: seeded random train/test split (optionally stratified; nulls form their own stratum),
or a chronological split where the test set is the latest rows by a date column."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from app.flows.blocks._common import BlockError, BlockOutput, Ctx, require
from app.flows.schemas import SplitConfig


def run(cfg: SplitConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"]
    if len(df) < 2:
        raise BlockError("need at least 2 rows to split")
    if cfg.mode == "chronological":
        return _chronological(cfg, df)
    strat = None
    if cfg.stratify is not None:
        require(df, [cfg.stratify], "stratify column")
        s = df[cfg.stratify]
        strat = s.astype(object).where(s.notna(), "(missing)").astype(str)
    try:
        tr, te = train_test_split(
            np.arange(len(df)),
            test_size=cfg.test_fraction,
            random_state=cfg.seed,
            stratify=strat,
        )
    except ValueError as e:
        raise BlockError(
            "cannot split: a stratum is too small for this test fraction"
            if strat is not None
            else "cannot split: too few rows for this test fraction"
        ) from e
    return BlockOutput(
        frames={
            "train": df.iloc[np.sort(tr)].reset_index(drop=True),
            "test": df.iloc[np.sort(te)].reset_index(drop=True),
        }
    )


def _chronological(cfg: SplitConfig, df: pd.DataFrame) -> BlockOutput:
    assert cfg.date_column is not None
    require(df, [cfg.date_column], "date column")
    try:
        d = pd.to_datetime(df[cfg.date_column])
    except (ValueError, TypeError) as e:
        raise BlockError(f"column '{cfg.date_column}' is not a date") from e
    ok = d.notna().to_numpy()
    warnings = []
    if not ok.all():
        warnings.append(f"{int((~ok).sum())} rows without a date left out of the split")
    idx = np.flatnonzero(ok)
    if len(idx) < 2:
        raise BlockError("need at least 2 dated rows to split")
    order = idx[np.argsort(d.to_numpy()[idx], kind="stable")]
    dates = d.to_numpy()[order]
    cut = len(order) - max(1, round(cfg.test_fraction * len(order)))
    cut = max(cut, 1)
    while cut > 0 and dates[cut - 1] == dates[cut]:
        cut -= 1  # rows sharing the boundary date all go to the test set: no overlap in time
    if cut == 0:
        raise BlockError("cannot split chronologically: the rows do not span enough dates")
    return BlockOutput(
        frames={
            "train": df.iloc[np.sort(order[:cut])].reset_index(drop=True),
            "test": df.iloc[np.sort(order[cut:])].reset_index(drop=True),
        },
        warnings=warnings,
    )
