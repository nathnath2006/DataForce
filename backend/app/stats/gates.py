"""The 'not verified' gates. Each function returns the list of failure reasons (empty = pass)."""

from __future__ import annotations

import math

from app.domain.enums import Metric
from app.domain.schemas import GateConfig


def _bad(x: float | None) -> bool:
    """Missing, NaN or infinite: every gate fails closed on these."""
    return x is None or not math.isfinite(x)


def ci_width_rate(
    low: float | None, high: float | None, cfg: GateConfig, label: str = ""
) -> list[str]:
    """CI half-width gate for a rate (fractions in, points out); fails closed on non-finite."""
    pre = f"{label}: " if label else ""
    if _bad(low) or _bad(high):
        return [f"{pre}CI not computable"]
    assert low is not None and high is not None
    half = (high - low) / 2 * 100
    if half > cfg.max_ci_halfwidth_pts + 1e-9:
        return [f"{pre}CI ±{half:.1f} pts > ±{cfg.max_ci_halfwidth_pts:g} pts"]
    return []


def ci_width_median(
    est: float | None, low: float | None, high: float | None, cfg: GateConfig, label: str = ""
) -> list[str]:
    """CI half-width gate for a median, relative to the estimate; fails closed on non-finite."""
    pre = f"{label}: " if label else ""
    if _bad(est) or _bad(low) or _bad(high):
        return [f"{pre}CI not computable"]
    assert est is not None and low is not None and high is not None
    half = (high - low) / 2
    if est == 0:
        return [f"{pre}median is 0: relative CI undefined"] if half > 0 else []
    rel = half / abs(est)
    if rel > cfg.max_ci_rel_halfwidth + 1e-9:
        return [f"{pre}CI ±{rel * 100:.0f}% of the median > ±{cfg.max_ci_rel_halfwidth * 100:g}%"]
    return []


def gate_rate(k: int, n: int, low: float | None, high: float | None, cfg: GateConfig) -> list[str]:
    """Win rate gates; k = wins, n = closed deals."""
    reasons: list[str] = []
    if n < cfg.min_n:
        reasons.append(f"n = {n} < {cfg.min_n}")
    if k < cfg.min_wins:
        reasons.append(f"only {k} wins (< {cfg.min_wins})")
    if n - k < cfg.min_losses:
        reasons.append(f"only {n - k} losses (< {cfg.min_losses})")
    if n >= cfg.min_n:
        reasons += ci_width_rate(low, high, cfg)
    return reasons


def gate_median(
    n: int, est: float | None, low: float | None, high: float | None, cfg: GateConfig
) -> list[str]:
    reasons: list[str] = []
    if n < cfg.min_n:
        reasons.append(f"n = {n} < {cfg.min_n}")
    if n >= cfg.min_n:
        reasons += ci_width_median(est, low, high, cfg)
    return reasons


def gate_side(metric: Metric, n: int, wins: int | None, cfg: GateConfig, label: str) -> list[str]:
    """n gates (plus wins/losses for win rate) for one side of a comparison."""
    reasons: list[str] = []
    if n < cfg.min_n:
        reasons.append(f"{label}: n = {n} < {cfg.min_n}")
    if metric is Metric.WIN_RATE:
        if wins is None:
            reasons.append(f"{label}: win count unknown")
        else:
            if wins < cfg.min_wins:
                reasons.append(f"{label}: only {wins} wins (< {cfg.min_wins})")
            if n - wins < cfg.min_losses:
                reasons.append(f"{label}: only {n - wins} losses (< {cfg.min_losses})")
    return reasons


def gate_finding(
    metric: Metric,
    n_group: int,
    wins_group: int | None,
    n_rest: int,
    wins_rest: int | None,
    q: float | None,
    diff_low: float | None,
    diff_high: float | None,
    cfg: GateConfig,
    side_ci_reasons: list[str] | None = None,
) -> list[str]:
    """`side_ci_reasons`: CI-width failures of each side, already labelled "group:"/"rest:"."""
    reasons = gate_side(metric, n_group, wins_group, cfg, "group")
    reasons += gate_side(metric, n_rest, wins_rest, cfg, "rest")
    reasons += side_ci_reasons or []
    if _bad(q):
        reasons.append("no p-value")
    else:
        assert q is not None
        if q >= cfg.fdr_alpha:
            reasons.append(f"q = {q:.3g} >= {cfg.fdr_alpha:g}")
    if _bad(diff_low) or _bad(diff_high):
        reasons.append("difference CI not computed")
    else:
        assert diff_low is not None and diff_high is not None
        if diff_low <= 0 <= diff_high:
            if metric == Metric.WIN_RATE:  # rates are fractions; reasons speak in points
                ci = f"[{diff_low * 100:+.1f}, {diff_high * 100:+.1f}] pts"
            elif metric == Metric.CYCLE_DAYS:
                ci = f"[{diff_low:+.1f}, {diff_high:+.1f}] days"
            else:  # amounts: whole euros, never scientific notation ("9.92e+03")
                ci = f"[{diff_low:+,.0f}, {diff_high:+,.0f}] EUR"
            reasons.append(f"difference CI {ci} includes 0")
    return reasons
