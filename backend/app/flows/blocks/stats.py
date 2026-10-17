"""stats: each group of `group_by` against the rest, with the M1 gates.

Rates and rate differences are fractions (0.10 = 10 points). A group is verified only when every
gate passes (n, wins/losses, CI widths, BH q-value, difference CI excluding 0), as in M1.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.domain.enums import Metric
from app.flows.blocks._boot import boot_medians, interval
from app.flows.blocks._common import BlockError, BlockOutput, Ctx, fnum, matches, require, to_float
from app.flows.schemas import StatsConfig, StatsRow, StatsView
from app.stats import gates as G
from app.stats.intervals import newcombe_diff, wilson
from app.stats.significance import benjamini_hochberg, fisher_2x2, mann_whitney

MAX_GROUPS = 50
BOOT_BUDGET = 2e8  # element draws: rows x resamples x (groups + 1)
MIN_RESAMPLES = 200
MULTIPLIED = "rows were duplicated by an upstream join, so n is inflated"


def _unit_free(reasons: list[str]) -> list[str]:
    return [r.replace(" EUR includes 0", " includes 0") for r in reasons]


def run(cfg: StatsConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"]
    require(df, [cfg.group_by, cfg.outcome])
    gc = ctx.gates
    rng = np.random.default_rng(gc.random_seed)
    grp = df[cfg.group_by]
    if cfg.outcome_kind == "rate":
        y = matches(df[cfg.outcome], cfg.success_value).astype(float)
        ok_out = df[cfg.outcome].notna()
        if ok_out.any() and not y[ok_out].any():
            raise BlockError(f"no row has {cfg.outcome} = {cfg.success_value!r}")
    else:
        y = to_float(df[cfg.outcome], cfg.outcome)
        ok_out = y.notna()
    ok = grp.notna() & ok_out
    excluded = int((~ok).sum())
    g = grp[ok].astype(str).reset_index(drop=True)
    v = y[ok].reset_index(drop=True).to_numpy(dtype=float)
    names = sorted(g.unique())
    if len(names) > MAX_GROUPS:
        raise BlockError(f"too many groups ({len(names)} > {MAX_GROUPS}): bucket or filter first")
    rate = cfg.outcome_kind == "rate"
    metric = Metric.WIN_RATE if rate else Metric.DEAL_AMOUNT

    warnings: list[str] = []
    resamples = gc.bootstrap_resamples
    if not rate and len(v):
        cost = len(v) * (len(names) + 1)
        if cost * resamples > BOOT_BUDGET:
            lowered = max(MIN_RESAMPLES, int(BOOT_BUDGET // cost))
            if lowered < resamples:
                warnings.append(
                    f"bootstrap resamples lowered from {resamples} to {lowered} to bound the work"
                )
                resamples = lowered
            if cost * resamples > BOOT_BUDGET * 1.25:
                raise BlockError("too many rows for a median comparison: filter or sample first")

    def bmed(vals: np.ndarray) -> tuple[np.ndarray, float, float, float]:
        boot = boot_medians(vals, resamples, rng, ctx)
        lo_, hi_ = interval(boot, gc.confidence)
        return boot, float(np.median(vals)), lo_, hi_

    def one(vals: np.ndarray) -> tuple[float, float, float]:
        if rate:
            return wilson(int(vals.sum()), len(vals), gc.confidence)
        _, m, lo_, hi_ = bmed(vals)
        return m, lo_, hi_

    def own_gate(n: int, est: float, lo: float, hi: float) -> list[str]:
        if rate:
            return G.gate_rate(int(round(est * n)) if n else 0, n, lo, hi, gc)
        return G.gate_median(n, fnum(est), fnum(lo), fnum(hi), gc)

    # overall
    n_all = len(v)
    est, lo, hi = one(v) if n_all else (math.nan,) * 3
    all_reasons = own_gate(n_all, est, lo, hi) if n_all else ["no rows"]
    if ctx.rows_multiplied:
        all_reasons = [*all_reasons, MULTIPLIED]
    overall = StatsRow(
        group="(all)",
        n=n_all,
        value=fnum(est),
        ci_low=fnum(lo),
        ci_high=fnum(hi),
        rest_value=None,
        diff=None,
        diff_ci_low=None,
        diff_ci_high=None,
        p_value=None,
        q_value=None,
        status="not_verified" if all_reasons else "verified",
        reasons=all_reasons,
    )

    pending = []
    gv = g.to_numpy()
    for name in names:
        ctx.check()
        m = gv == name
        a, b = v[m], v[~m]
        n1, n2 = len(a), len(b)
        side: list[str] = []
        k1 = k2 = None
        if rate:
            k1, k2 = int(a.sum()), int(b.sum())
            p = fisher_2x2(k1, n1, k2, n2)
            e1, l1, h1 = wilson(k1, n1, gc.confidence)
            rv = k2 / n2 if n2 else math.nan
            d, dlo, dhi = newcombe_diff(k1, n1, k2, n2, gc.confidence)
            if n1 >= gc.min_n:
                side += G.ci_width_rate(l1, h1, gc, "group")
            if n2 >= gc.min_n:
                side += G.ci_width_rate(*wilson(k2, n2, gc.confidence)[1:], gc, "rest")
        else:
            p = mann_whitney(a, b)
            if n1:
                boot_a, e1, l1, h1 = bmed(a)
            else:
                boot_a, e1, l1, h1 = np.empty(0), math.nan, math.nan, math.nan
            rv = float(np.median(b)) if n2 else math.nan
            if n1 >= gc.min_n and n2 >= gc.min_n:
                boot_b, est2, l2, h2 = bmed(b)
                dlo, dhi = interval(boot_a - boot_b, gc.confidence)
                d = e1 - rv
                side += G.ci_width_median(e1, l1, h1, gc, "group")
                side += G.ci_width_median(est2, l2, h2, gc, "rest")
            else:
                d = e1 - rv if n1 and n2 else math.nan
                dlo = dhi = math.nan
        pending.append((name, n1, n2, k1, k2, e1, l1, h1, rv, d, dlo, dhi, p, side))

    qs = benjamini_hochberg([x[12] for x in pending])
    rows: list[StatsRow] = []
    for (name, n1, n2, k1, k2, e1, l1, h1, rv, d, dlo, dhi, p, side), q in zip(
        pending, qs, strict=True
    ):
        qv = fnum(q)
        reasons = _unit_free(
            G.gate_finding(metric, n1, k1, n2, k2, qv, fnum(dlo), fnum(dhi), gc, side)
        )
        if ctx.rows_multiplied:
            reasons.append(MULTIPLIED)
        rows.append(
            StatsRow(
                group=name,
                n=n1,
                value=fnum(e1),
                ci_low=fnum(l1),
                ci_high=fnum(h1),
                rest_value=fnum(rv),
                diff=fnum(d),
                diff_ci_low=fnum(dlo),
                diff_ci_high=fnum(dhi),
                p_value=fnum(p),
                q_value=qv,
                status="not_verified" if reasons else "verified",
                reasons=reasons,
            )
        )
    table = pd.DataFrame([r.model_dump() for r in rows])
    if table.empty:
        table = pd.DataFrame(columns=list(StatsRow.model_fields))
    else:
        table["reasons"] = table["reasons"].map("; ".join)
    method = "wilson + newcombe + fisher, BH" if rate else "bootstrap median + mann-whitney, BH"
    if excluded:
        warnings.append(f"{excluded} rows with a missing group or outcome excluded")
    view = StatsView(
        outcome=cfg.outcome,
        outcome_kind=cfg.outcome_kind,
        method=method,
        overall=overall,
        rows=rows,
        excluded_missing=excluded,
        gates=gc.model_dump(),
    )
    return BlockOutput(frames={"out": table}, view=view, warnings=warnings)
