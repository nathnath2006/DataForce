"""velocity: deal velocity from stage-change events.

Days in a stage = time from the event that entered it to the next event of the same deal. A
completed stay (the deal moved on) is ranked within the completed stays of the same stage: its
percentile (0 = the fastest, 1 = the slowest; ties share their mid-rank). A deal's index is the
median of its stays' percentiles, not the geometric mean of ratios: it is bounded, ignores one
extreme stay, and its quartile thresholds (fast track at or below 0.25, stagnant at or above
0.75) have a plain meaning. Identical deals all sit at 0.5 and get no flag.

A stage needs `min_stage_n` completed stays; otherwise its stays are "insufficient data" and a
deal with no qualifying stage gets no flag, with a reason. The stay a deal is in now (open) is
reported apart and never enters the benchmark: it is `stalled_in_stage` when its age already
exceeds the p75 of the completed stays of its stage.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.flows.blocks._common import BlockError, BlockOutput, Ctx, fnum, require
from app.flows.schemas import VelocityConfig, VelocityStage, VelocityView

MAX_STAGES = 30
NOTE = (
    "Each completed stay is ranked against the completed stays of the same stage in this input "
    "(not an industry figure); a deal's index is the median of its stays' percentiles, 0 fastest "
    "and 1 slowest. Open stays are reported separately and are not part of the benchmark."
)


def _slug(stage: str) -> str:
    return "days_in_" + "".join(c if c.isalnum() else "_" for c in stage.lower())[:60]


def _percentile(vals: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """Mid-rank share of `ref` below each value of `vals`."""
    ref = np.sort(ref)
    lo = np.searchsorted(ref, vals, side="left")
    hi = np.searchsorted(ref, vals, side="right")
    return (lo + hi) / 2.0 / len(ref)


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

    # completed stays (a deal re-entering a stage adds up) and the benchmark of each stage
    done = ev[~ev["open"]].groupby(["deal", "stage"])["days"].sum().rename("days").reset_index()
    bench = done.groupby("stage")["days"].agg(
        n="size", median="median", p75=lambda x: float(np.quantile(x, 0.75))
    )
    bench["ok"] = bench["n"] >= cfg.min_stage_n
    thin = bench[~bench["ok"]]
    if len(thin):
        warnings.append(
            f"{len(thin)} stage(s) have fewer than {cfg.min_stage_n} completed stays: "
            "insufficient data, left out of the index"
        )
    done["pct"] = np.nan
    for stage, grp in done.groupby("stage"):
        if bench.loc[stage, "ok"]:
            done.loc[grp.index, "pct"] = _percentile(grp["days"].to_numpy(), grp["days"].to_numpy())
    scored = done.dropna(subset=["pct"])
    by_deal = scored.groupby("deal", sort=False)["pct"].agg(["median", "size"])

    ev_all = ev.groupby(["deal", "stage"], sort=False)["days"].sum().reset_index()
    agg = ev_all.groupby("deal", sort=False).agg(
        n_stages=("stage", "size"), total_days=("days", "sum")
    )
    agg["n_stages_scored"] = by_deal["size"].reindex(agg.index).fillna(0).astype(int)
    idx = by_deal["median"].reindex(agg.index)
    flag = pd.Series(pd.NA, index=agg.index, dtype="object").where(idx.isna(), "normal")
    flag[idx <= cfg.fast_track_pct] = "fast_track"
    flag[idx >= cfg.stagnant_pct] = "stagnant"
    reason = pd.Series("", index=agg.index, dtype="object")
    has_done = set(done["deal"])
    for d in agg.index[idx.isna()]:
        reason[d] = (
            f"no stage with at least {cfg.min_stage_n} completed stays"
            if d in has_done
            else "no completed stay yet"
        )

    out = agg.reset_index().rename(columns={"deal": cfg.deal_column})
    out["velocity_percentile"] = idx.to_numpy()
    out["velocity_flag"] = flag.to_numpy()
    out["velocity_reason"] = reason.replace("", None).to_numpy()

    # open stays, apart from the benchmark
    op = ev[ev["open"]].groupby("deal", sort=False).last()[["stage", "days"]]
    p75 = op["stage"].map(bench["p75"])
    sufficient = op["stage"].map(bench["ok"]).fillna(False).astype(bool)
    op["stalled"] = (op["days"] > p75) & sufficient
    out["open_stage"] = out[cfg.deal_column].map(op["stage"])
    out["open_days"] = out[cfg.deal_column].map(op["days"])
    out["stalled_in_stage"] = out[cfg.deal_column].map(op["stalled"]).fillna(False).astype(bool)
    n_stalled = int(op["stalled"].sum())

    top = ev_all["stage"].value_counts().index[:MAX_STAGES]
    if ev_all["stage"].nunique() > MAX_STAGES:
        warnings.append(f"per-stage day columns limited to the {MAX_STAGES} most common stages")
    wide = ev_all[ev_all["stage"].isin(top)].pivot_table(
        index="deal", columns="stage", values="days", aggfunc="sum"
    )
    wide.columns = [_slug(str(c)) for c in wide.columns]
    wide = wide.reset_index().rename(columns={"deal": cfg.deal_column})
    out = out.merge(wide, on=cfg.deal_column, how="left")
    n_null = int(idx.isna().sum())
    if n_null:
        warnings.append(f"{n_null} deals have no stage with enough completed stays: no flag")
    counts = {k: int((flag == k).sum()) for k in ("fast_track", "normal", "stagnant")}
    counts["no_flag"] = n_null
    view = VelocityView(
        benchmark_note=NOTE,
        benchmarks=[
            VelocityStage(
                stage=str(s),
                median_days=fnum(r["median"]),
                n=int(r["n"]),
                p75_days=fnum(r["p75"]),
                sufficient=bool(r["ok"]),
            )
            for s, r in bench.sort_values("n", ascending=False).iterrows()
        ],
        fast_track_pct=cfg.fast_track_pct,
        stagnant_pct=cfg.stagnant_pct,
        min_stage_n=cfg.min_stage_n,
        counts=counts,
        n_stalled=n_stalled,
    )
    return BlockOutput(frames={"out": out}, view=view, warnings=warnings)
