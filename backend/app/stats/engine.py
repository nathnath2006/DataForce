"""Stats engine: overall numbers, per-group numbers and the segment scan. Pure and seeded."""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import numpy as np

from app.config import Settings
from app.domain.enums import Dimension, Metric, StatStatus
from app.domain.schemas import EffectFinding, GateConfig, GroupStats, ScanReport, StatValue
from app.stats import gates
from app.stats.intervals import bootstrap_median, bootstrap_median_diff, newcombe_diff, wilson
from app.stats.rows import DealRow, clean_rows, value_of
from app.stats.significance import benjamini_hochberg, fisher_2x2, mann_whitney

ALL_DIMENSIONS: tuple[Dimension, ...] = tuple(Dimension)
METRICS: tuple[Metric, ...] = (Metric.WIN_RATE, Metric.CYCLE_DAYS, Metric.DEAL_AMOUNT)


def gate_config_from_settings(settings: Settings) -> GateConfig:
    return GateConfig(
        confidence=settings.stats_confidence,
        fdr_alpha=settings.stats_fdr_alpha,
        min_n=settings.gate_min_n,
        min_wins=settings.gate_min_wins,
        min_losses=settings.gate_min_losses,
        max_ci_halfwidth_pts=settings.gate_max_ci_halfwidth_pts,
        max_ci_rel_halfwidth=settings.gate_max_ci_rel_halfwidth,
        bootstrap_resamples=settings.stats_bootstrap_resamples,
        random_seed=settings.stats_random_seed,
    )


def _f(x: float) -> float | None:
    return None if math.isnan(x) else float(x)


def _metric_values(rows: Sequence[DealRow], metric: Metric) -> list[float]:
    """Per-row numbers for a metric (win rate: 1.0 won / 0.0 lost, closed deals only)."""
    out: list[float] = []
    for r in rows:
        if metric is Metric.WIN_RATE:
            if r.won is not None:
                out.append(1.0 if r.won else 0.0)
        elif metric is Metric.CYCLE_DAYS:
            if r.cycle_days is not None:
                out.append(r.cycle_days)
        elif r.amount is not None:
            out.append(float(r.amount))
    return out


def _stat(
    metric: Metric,
    values: list[float],
    cfg: GateConfig,
    rng: np.random.Generator,
    extra: dict[str, Any] | None = None,
) -> StatValue:
    n = len(values)
    details: dict[str, Any] = dict(extra or {})
    if metric is Metric.WIN_RATE:
        k = int(sum(values))
        est, lo, hi = wilson(k, n, cfg.confidence)
        reasons = gates.gate_rate(k, n, lo, hi, cfg)
        details.update(wins=k, losses=n - k)
        method = "wilson"
    else:
        est, lo, hi = bootstrap_median(values, cfg.confidence, cfg.bootstrap_resamples, rng)
        reasons = gates.gate_median(n, _f(est), _f(lo), _f(hi), cfg)
        method = "bootstrap-percentile median"
    return StatValue(
        metric=metric,
        value=_f(est),
        ci_low=_f(lo),
        ci_high=_f(hi),
        n=n,
        method=method,
        status=StatStatus.NOT_VERIFIED if reasons else StatStatus.VERIFIED,
        reasons=reasons,
        details=details,
    )


def overall(
    rows: Sequence[DealRow], cfg: GateConfig, rng: np.random.Generator | None = None
) -> dict[Metric, StatValue]:
    rng = rng if rng is not None else np.random.default_rng(cfg.random_seed)
    rows = clean_rows(rows).rows
    return {m: _stat(m, _metric_values(rows, m), cfg, rng) for m in METRICS}


def _metrics_for(dim: Dimension) -> tuple[Metric, ...]:
    if dim is Dimension.AMOUNT_BAND:  # tautological: the band is defined by the amount
        return (Metric.WIN_RATE, Metric.CYCLE_DAYS)
    return METRICS


def _split(rows: Sequence[DealRow], dim: Dimension) -> dict[str, list[DealRow]]:
    groups: dict[str, list[DealRow]] = {}
    for r in rows:
        v = value_of(r, dim)
        if v is not None:
            groups.setdefault(v, []).append(r)
    return {k: groups[k] for k in sorted(groups)}


def group_stats(
    rows: Sequence[DealRow],
    dim: Dimension,
    cfg: GateConfig,
    rng: np.random.Generator | None = None,
) -> list[GroupStats]:
    rng = rng if rng is not None else np.random.default_rng(cfg.random_seed)
    rows = clean_rows(rows).rows
    return [
        GroupStats(
            dimension=dim,
            group=g,
            n_deals=len(grp),
            stats={m: _stat(m, _metric_values(grp, m), cfg, rng) for m in _metrics_for(dim)},
        )
        for g, grp in _split(rows, dim).items()
    ]


def _compare(
    dim: Dimension,
    group: str,
    metric: Metric,
    a: list[DealRow],
    b: list[DealRow],
    cfg: GateConfig,
    rng: np.random.Generator,
) -> tuple[EffectFinding, int | None, int | None, list[str]]:
    xa, xb = _metric_values(a, metric), _metric_values(b, metric)
    n1, n2 = len(xa), len(xb)
    wins1 = wins2 = None
    if metric is Metric.WIN_RATE:
        wins1, wins2 = int(sum(xa)), int(sum(xb))
        test = "fisher-exact"
        p = fisher_2x2(wins1, n1, wins2, n2)
        gv = wins1 / n1 if n1 else math.nan
        rv = wins2 / n2 if n2 else math.nan
        diff, lo, hi = newcombe_diff(wins1, n1, wins2, n2, cfg.confidence)
        side: list[str] = []
        if n1 >= cfg.min_n:
            side += gates.ci_width_rate(*wilson(wins1, n1, cfg.confidence)[1:], cfg, "group")
        if n2 >= cfg.min_n:
            side += gates.ci_width_rate(*wilson(wins2, n2, cfg.confidence)[1:], cfg, "rest")
    else:
        test = "mann-whitney-u"
        p = mann_whitney(xa, xb)
        gv = float(np.median(xa)) if n1 else math.nan
        rv = float(np.median(xb)) if n2 else math.nan
        if n1 >= cfg.min_n and n2 >= cfg.min_n:  # the CI only matters when the n gates pass
            diff, lo, hi = bootstrap_median_diff(
                xa, xb, cfg.confidence, cfg.bootstrap_resamples, rng
            )
        else:
            diff, lo, hi = (gv - rv, math.nan, math.nan) if n1 and n2 else (math.nan,) * 3
        side = []
        for label, x, n_side in (("group", xa, n1), ("rest", xb, n2)):
            if n_side >= cfg.min_n:  # below min-n the n gate already fails the side
                est, slo, shi = bootstrap_median(x, cfg.confidence, cfg.bootstrap_resamples, rng)
                side += gates.ci_width_median(est, slo, shi, cfg, label)
    d = _f(diff)
    direction = "none" if d is None or d == 0 else ("higher" if d > 0 else "lower")
    f = EffectFinding(
        dimension=dim,
        group=group,
        metric=metric,
        group_value=_f(gv),
        rest_value=_f(rv),
        diff=d,
        diff_ci_low=_f(lo),
        diff_ci_high=_f(hi),
        p_value=_f(p),
        q_value=None,
        test=test,
        n_group=n1,
        n_rest=n2,
        direction=direction,  # type: ignore[arg-type]
        status=StatStatus.NOT_VERIFIED,
        reasons=[],
    )
    return f, wins1, wins2, side


def scan(
    rows: Sequence[DealRow],
    cfg: GateConfig,
    *,
    dimensions: Sequence[Dimension] = ALL_DIMENSIONS,
    workspace_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
) -> ScanReport:
    """Compare every dimension x group x metric (group vs rest), BH across all p-values.

    Deterministic: same rows, cfg (incl. random_seed) and `created_at` give identical JSON.
    `created_at` defaults to now; pass a fixed value to compare reports byte for byte.
    """
    rng = np.random.default_rng(cfg.random_seed)
    cleaned = clean_rows(rows)
    rows = cleaned.rows
    n_closed = sum(1 for r in rows if r.won is not None)
    missing: dict[str, int] = {}
    for dim in dimensions:
        missing[dim.value] = sum(1 for r in rows if value_of(r, dim) is None)
    missing["closed_on"] = sum(1 for r in rows if r.won is not None and r.closed_on is None)
    missing["amount"] = sum(1 for r in rows if r.amount is None)
    missing["duplicate_deals"] = cleaned.duplicates
    missing["negative_cycle"] = cleaned.negative_cycle
    missing["invalid_amount"] = cleaned.invalid_amount

    groups: list[GroupStats] = []
    pending: list[tuple[EffectFinding, int | None, int | None, list[str]]] = []
    for dim in dimensions:
        groups.extend(group_stats(rows, dim, cfg, rng))
        split = _split(rows, dim)
        for g, grp in split.items():
            rest = [r for h, other in split.items() if h != g for r in other]
            for m in _metrics_for(dim):
                pending.append(_compare(dim, g, m, grp, rest, cfg, rng))

    qs = benjamini_hochberg(
        [f.p_value if f.p_value is not None else math.nan for f, _, _, _ in pending]
    )
    findings: list[EffectFinding] = []
    for (f, w1, w2, side), q in zip(pending, qs, strict=True):
        qv = _f(q)
        reasons = gates.gate_finding(
            f.metric, f.n_group, w1, f.n_rest, w2, qv, f.diff_ci_low, f.diff_ci_high, cfg, side
        )
        findings.append(
            f.model_copy(
                update={
                    "q_value": qv,
                    "reasons": reasons,
                    "status": StatStatus.NOT_VERIFIED if reasons else StatStatus.VERIFIED,
                }
            )
        )

    n_tests = len(findings)
    n_ver = sum(1 for f in findings if f.status is StatStatus.VERIFIED)
    notes = [
        f"{n_tests} comparisons (group vs rest) were tested; {n_ver} verified.",
        f"A finding is verified only if both sides have n >= {cfg.min_n} (win rate: also >= "
        f"{cfg.min_wins} wins and >= {cfg.min_losses} losses), the Benjamini-Hochberg q-value "
        f"over all {n_tests} tests is < {cfg.fdr_alpha:g}, and the {cfg.confidence:.0%} CI of "
        "the difference excludes 0.",
        f"A group statistic is verified when n >= {cfg.min_n} (win rate: also the wins/losses "
        f"minimums) and its CI is narrow enough (rates: half-width <= {cfg.max_ci_halfwidth_pts:g} "
        f"pts; medians: <= {cfg.max_ci_rel_halfwidth:.0%} of the median).",
        "'Not verified' does not mean 'no effect': it means the data cannot establish it.",
        "Rates and rate differences are fractions (0.10 = 10 points); cycle is in days, amount in "
        "EUR. Missing values are excluded per dimension and counted in `missing`.",
        "amount_band x deal_amount is not tested (the band is defined by the amount).",
        "A finding also needs the CI of each side to pass the width gate (reasons are labelled "
        "'group:' and 'rest:').",
    ]
    if cleaned.duplicates:
        notes.append(f"{cleaned.duplicates} duplicate deal id(s) were dropped (first one kept).")
    if cleaned.negative_cycle:
        notes.append(
            f"{cleaned.negative_cycle} closed deal(s) with closed_on before created_on were "
            "excluded from cycle length (their win/loss is still counted)."
        )
    if cleaned.invalid_amount:
        notes.append(
            f"{cleaned.invalid_amount} deal(s) with a negative or non-finite amount were treated "
            "as missing amounts."
        )
    return ScanReport(
        workspace_id=workspace_id,
        created_at=created_at or datetime.now(UTC),
        n_deals=len(rows),
        n_closed=n_closed,
        n_open=len(rows) - n_closed,
        gates=cfg,
        overall=overall(rows, cfg, rng),
        groups=groups,
        findings=findings,
        missing=missing,
        notes=notes,
    )
