"""velocity: deal velocity index from stage-change events.

Days in a stage = time from the event that entered it to the next event of the same deal. The
stage a deal is in now (not a terminal one) counts up to the run date when `include_open_stage`.
Benchmark of a stage = the median, over the input rows, of the days deals spent in it (completed
stays only). velocity_index = sum of benchmarks / sum of actual days over the stages the deal
passed through; above `fast_track_at` is fast_track, below `stagnant_below` is stagnant.
"""

from __future__ import annotations

import pandas as pd

from app.flows.blocks._common import BlockError, BlockOutput, Ctx, fnum, require
from app.flows.schemas import VelocityConfig, VelocityStage, VelocityView

MAX_STAGES = 30
NOTE = (
    "The benchmark of a stage is the median days deals spent in it, computed over the rows of "
    "this input (completed stays only); it is not an industry figure."
)


def _slug(stage: str) -> str:
    return "days_in_" + "".join(c if c.isalnum() else "_" for c in stage.lower())[:60]


def run(cfg: VelocityConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"]
    require(df, [cfg.deal_column, cfg.to_stage_column, cfg.date_column])
    try:
        when = pd.to_datetime(df[cfg.date_column])
    except (ValueError, TypeError) as e:
        raise BlockError(f"column '{cfg.date_column}' is not a date") from e
    if getattr(when.dt, "tz", None) is not None:
        when = when.dt.tz_localize(None)
    ev = pd.DataFrame({"deal": df[cfg.deal_column], "stage": df[cfg.to_stage_column], "at": when})
    bad = int(ev.isna().any(axis=1).sum())
    ev = ev.dropna()
    warnings = [f"{bad} rows with a missing deal, stage or date ignored"] if bad else []
    ev["stage"] = ev["stage"].astype(str)
    ev = ev.sort_values(["deal", "at"], kind="stable").reset_index(drop=True)
    today = pd.Timestamp(ctx.today)
    nxt = ev.groupby("deal", sort=False)["at"].shift(-1)
    last = nxt.isna()
    terminal = ev["stage"].isin(cfg.terminal_stages)
    open_stay = last & ~terminal
    end = nxt.where(~open_stay, today)
    ev["days"] = ((end - ev["at"]).dt.total_seconds() / 86400.0).clip(lower=0)
    ev.loc[last & terminal, "days"] = float("nan")
    ev["open"] = open_stay
    ev = ev[ev["days"].notna()]
    if not cfg.include_open_stage:
        ev = ev[~ev["open"]]

    done = ev[~ev["open"]].groupby(["deal", "stage"])["days"].sum()
    bench = done.groupby("stage").agg(["median", "size"])
    per = ev.groupby(["deal", "stage"], sort=False)["days"].sum().reset_index()
    per = per[per["stage"].isin(bench.index)]  # a stage nobody completed has no benchmark
    per["bench"] = per["stage"].map(bench["median"])
    agg = per.groupby("deal", sort=False).agg(
        n_stages=("stage", "size"), total_days=("days", "sum"), benchmark_days=("bench", "sum")
    )
    actual = agg["total_days"]
    idx = (agg["benchmark_days"] / actual).where(actual > 0)
    flag = pd.Series(pd.NA, index=agg.index, dtype="object").where(idx.isna(), "normal")
    flag[idx >= cfg.fast_track_at] = "fast_track"
    flag[idx < cfg.stagnant_below] = "stagnant"
    out = agg.reset_index().rename(columns={"deal": cfg.deal_column})
    out["velocity_index"] = idx.to_numpy()
    out["velocity_flag"] = flag.to_numpy()
    top = per["stage"].value_counts().index[:MAX_STAGES]
    if per["stage"].nunique() > MAX_STAGES:
        warnings.append(f"per-stage day columns limited to the {MAX_STAGES} most common stages")
    wide = per[per["stage"].isin(top)].pivot_table(
        index="deal", columns="stage", values="days", aggfunc="sum"
    )
    wide.columns = [_slug(str(c)) for c in wide.columns]
    wide = wide.reset_index().rename(columns={"deal": cfg.deal_column})
    out = out.merge(wide, on=cfg.deal_column, how="left")
    n_null = int(idx.isna().sum())
    if n_null:
        warnings.append(f"{n_null} deals have no benchmarked time in a stage: no index")
    counts = {k: int((flag == k).sum()) for k in ("fast_track", "normal", "stagnant")}
    counts["no_index"] = n_null
    view = VelocityView(
        benchmark_note=NOTE,
        benchmarks=[
            VelocityStage(stage=str(s), median_days=fnum(r["median"]), n=int(r["size"]))
            for s, r in bench.sort_values("size", ascending=False).iterrows()
        ],
        fast_track_at=cfg.fast_track_at,
        stagnant_below=cfg.stagnant_below,
        counts=counts,
    )
    return BlockOutput(frames={"out": out}, view=view, warnings=warnings)
