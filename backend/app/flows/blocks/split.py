"""split: seeded random train/test split, optionally stratified (nulls form their own stratum)."""

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
