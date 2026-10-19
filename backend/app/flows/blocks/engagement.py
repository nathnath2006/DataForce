"""engagement: a per-account engagement score that shows its working.

score = sum over activities in the last `window_days` days of weight[kind], times (1 - penalty)
when the latest touchpoint is more than `quiet_days` days before the run date (or there is none
up to that date). Activities dated after the run date are ignored.
"""

from __future__ import annotations

import pandas as pd

from app.flows.blocks._common import BlockError, BlockOutput, Ctx, require
from app.flows.schemas import EngagementConfig, EngagementView

MAX_KINDS = 20


def run(cfg: EngagementConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"]
    require(df, [cfg.by, cfg.kind_column, cfg.date_column])
    try:
        when = pd.to_datetime(df[cfg.date_column])
    except (ValueError, TypeError) as e:
        raise BlockError(f"column '{cfg.date_column}' is not a date") from e
    if getattr(when.dt, "tz", None) is not None:
        when = when.dt.tz_localize(None)
    weights = {k.strip().lower(): float(v) for k, v in cfg.weights.items()}
    default = weights.get("other", 1.0)
    today = pd.Timestamp(ctx.today)
    ev = pd.DataFrame(
        {
            "by": df[cfg.by],
            "kind": df[cfg.kind_column].astype(str).str.strip().str.lower(),
            "days_ago": (today - when.dt.normalize()).dt.days,
        }
    )
    warnings: list[str] = []
    keys = ev["by"].dropna().drop_duplicates()
    ev = ev[ev["by"].notna()]
    n_bad = int(ev["days_ago"].isna().sum())
    n_future = int((ev["days_ago"] < 0).sum())
    ev = ev[ev["days_ago"] >= 0]
    if n_bad:
        warnings.append(f"{n_bad} rows without a date ignored")
    if n_future:
        warnings.append(f"{n_future} rows dated after the run date ignored")
    ev["bucket"] = ev["kind"].where(ev["kind"].isin(weights), "other")
    ev["w"] = ev["bucket"].map(lambda k: weights.get(k, default))
    win = ev[ev["days_ago"] < cfg.window_days]
    buckets = sorted(set(weights) | {"other"})[:MAX_KINDS]
    counts = (
        win.groupby(["by", "bucket"]).size().unstack(fill_value=0).reindex(columns=buckets)
    ).fillna(0)
    res = pd.DataFrame({"by": keys.to_numpy()}).set_index("by")
    for b in buckets:
        res[f"n_{b}"] = counts[b].reindex(res.index).fillna(0).astype(int)
    res["raw_score"] = win.groupby("by")["w"].sum().reindex(res.index).fillna(0.0)
    last = ev.groupby("by")["days_ago"].min().reindex(res.index)
    res["days_since_last"] = last
    quiet = last.isna() | (last > cfg.quiet_days)
    res["penalty_applied"] = quiet.to_numpy(dtype=bool)
    res["engagement_score"] = res["raw_score"] * (1.0 - cfg.penalty * quiet.astype(float))
    out = res.reset_index().rename(columns={"by": cfg.by})
    out = out.sort_values(cfg.by, kind="stable").reset_index(drop=True)
    view = EngagementView(
        today=today.date().isoformat(),
        window_days=cfg.window_days,
        quiet_days=cfg.quiet_days,
        penalty=cfg.penalty,
        weights={k: v for k, v in weights.items()},
        n_accounts=len(out),
        n_penalised=int(quiet.sum()),
        caveats=[
            "accounts with no activity at all are absent from this table, not scored 0: join to "
            "the accounts table to list them",
            "the score drops by the penalty at once when the last touchpoint passes the quiet "
            "limit (a cliff, not a decay)",
        ],
        formula=(
            f"engagement_score = sum of weights of activities in the last {cfg.window_days} days"
            f" x (1 - {cfg.penalty:g}) when the last touchpoint is more than {cfg.quiet_days}"
            " days old"
        ),
    )
    warnings.append("heuristic: a weighted count, not a verified measure")
    return BlockOutput(frames={"out": out}, view=view, warnings=warnings)
