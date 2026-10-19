"""touchpoint: rep touchpoint ratio = meetings x weight / outreach (outbound calls and emails)."""

from __future__ import annotations

import pandas as pd

from app.flows.blocks._common import BlockOutput, Ctx, require
from app.flows.schemas import TouchpointConfig, TouchpointView


def run(cfg: TouchpointConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"]
    require(df, [cfg.by, cfg.kind_column, cfg.direction_column])
    kind = df[cfg.kind_column].astype(str).str.strip().str.lower()
    direction = df[cfg.direction_column].astype(str).str.strip().str.lower()
    has = df[cfg.by].notna()
    warnings: list[str] = []
    if int((~has).sum()):
        warnings.append(f"{int((~has).sum())} rows without a '{cfg.by}' ignored")
    t = pd.DataFrame(
        {
            "by": df.loc[has, cfg.by],
            "meetings": (kind == "meeting")[has].astype(int),
            "outbound_calls": ((kind == "call") & (direction == "outbound"))[has].astype(int),
            "emails": (kind == "email")[has].astype(int),
        }
    )
    g = t.groupby("by", sort=True).sum().reset_index()
    g["outreach"] = g["outbound_calls"] + g["emails"]
    enough = g["outreach"] >= cfg.min_outreach
    g["touchpoint_ratio"] = (g["meetings"] * cfg.meeting_weight) / g["outreach"].where(enough)
    g["touchpoint_reason"] = pd.Series(
        [
            None
            if ok
            else f"fewer than {cfg.min_outreach} outreach ({o}): the ratio is too noisy to show"
            for ok, o in zip(enough, g["outreach"], strict=True)
        ],
        index=g.index,
        dtype="object",
    )
    n_zero = int((g["outreach"] == 0).sum())
    n_low = int((~enough).sum())
    if n_zero:
        warnings.append(f"{n_zero} groups have no outreach: their ratio is empty, not infinite")
    if n_low - n_zero:
        warnings.append(
            f"{n_low - n_zero} groups have fewer than {cfg.min_outreach} outreach: ratio empty"
        )
    if n_low < len(g):
        warnings.append(
            "no confidence interval is shown: meetings are not a subset of outreach, so a Wilson "
            "interval does not apply"
        )
    out = g.rename(columns={"by": cfg.by})
    view = TouchpointView(
        formula=(
            f"touchpoint_ratio = meetings x {cfg.meeting_weight:g} / outreach, where outreach ="
            " outbound calls + emails"
        ),
        n_groups=len(out),
        n_no_outreach=n_zero,
        min_outreach=cfg.min_outreach,
        n_below_min=n_low,
    )
    return BlockOutput(frames={"out": out}, view=view, warnings=warnings)
