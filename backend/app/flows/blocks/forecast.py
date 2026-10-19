"""forecast: weighted amount = amount x stage probability. Probabilities are assumptions."""

from __future__ import annotations

import pandas as pd

from app.flows.blocks._common import BlockError, BlockOutput, Ctx, require, to_float
from app.flows.schemas import ForecastConfig


def _key(s: object) -> str:
    return str(s).strip().casefold().replace(" ", "_").replace("-", "_")


def run(cfg: ForecastConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"]
    require(df, [cfg.amount, cfg.stage])
    if cfg.group_by:
        require(df, [cfg.group_by])
    for name in ("probability", "weighted_amount"):
        if name in df.columns:
            raise BlockError(f"the input already has a column named '{name}'")
    probs = {_key(k): v for k, v in cfg.probabilities.items()}
    amount = to_float(df[cfg.amount], cfg.amount)
    prob = df[cfg.stage].map(lambda s: probs.get(_key(s)) if pd.notna(s) else None)
    prob = pd.to_numeric(prob, errors="coerce").astype("float64")
    out = df.copy()
    out["probability"] = prob
    out["weighted_amount"] = amount * prob / 100
    warnings = []
    unmapped = int((prob.isna() & amount.notna()).sum())
    if unmapped:
        warnings.append(f"{unmapped} rows have a stage without a probability: not weighted")
    warnings.append("probabilities are your assumptions, not a statistical estimate")
    if cfg.group_by:
        g = pd.DataFrame(
            {
                cfg.group_by: df[cfg.group_by],
                "n": 1,
                "amount": amount,
                "weighted_amount": out["weighted_amount"],
            }
        )
        out = (
            g.groupby(cfg.group_by, dropna=False, sort=True)
            .agg(
                n=("n", "sum"),
                amount=("amount", lambda s: s.sum(min_count=1)),
                weighted_amount=("weighted_amount", lambda s: s.sum(min_count=1)),
            )
            .reset_index()
        )
    return BlockOutput(frames={"out": out.reset_index(drop=True)}, warnings=warnings)
