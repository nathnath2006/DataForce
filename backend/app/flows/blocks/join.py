"""join: inner or left on key pairs. Null keys never match. The output is capped."""

from __future__ import annotations

import pandas as pd

from app.flows.blocks._common import BlockError, BlockOutput, Ctx, dtype_of, require
from app.flows.schemas import JoinConfig


def _family(kind: str) -> str:
    return "num" if kind in ("number", "integer") else kind


def run(cfg: JoinConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    left, right = inputs["left"], inputs["right"]
    lk = [k.left for k in cfg.on]
    rk = [k.right for k in cfg.on]
    require(left, lk, "left key")
    require(right, rk, "right key")
    for a, b in zip(lk, rk, strict=True):
        ka, kb = _family(dtype_of(left[a])), _family(dtype_of(right[b]))
        if ka != kb and "other" not in (ka, kb):
            raise BlockError(f"cannot join '{a}' ({ka}) with '{b}' ({kb}): different types")
    names = [f"__k{i}" for i in range(len(lk))]
    lkeys = left[lk].set_axis(names, axis=1)
    rkeys = right[rk].set_axis(names, axis=1)
    rvalid = rkeys.notna().all(axis=1)
    right_ok = right[rvalid.to_numpy()]
    counts = rkeys[rvalid].groupby(names).size().rename("__n").reset_index()
    per_left = lkeys.merge(counts, on=names, how="left")["__n"].fillna(0).to_numpy()
    if cfg.how == "left":
        per_left = per_left.clip(min=1)
    warnings: list[str] = []
    cum = per_left.cumsum()
    max_rows = ctx.limits.max_rows
    if len(cum) and cum[-1] > max_rows:
        keep = int((cum <= max_rows).sum())
        left = left.iloc[:keep]
        warnings.append(f"rows capped at {max_rows}")
    lm = left.reset_index(drop=True)
    out = lm.merge(
        right_ok.reset_index(drop=True),
        how=cfg.how,
        left_on=lk,
        right_on=rk,
        suffixes=("", cfg.suffix),
    )
    multiplied = len(out) > len(inputs["left"])
    if multiplied:
        warnings.append(
            "rows multiplied by the join (more output rows than the left input); "
            "counts downstream are inflated"
        )
    return BlockOutput(
        frames={"out": out.head(max_rows).reset_index(drop=True)},
        warnings=warnings,
        rows_multiplied=multiplied,
    )
