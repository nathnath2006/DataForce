"""Hypothesis tests and multiplicity control.

- Fisher (1935) exact test, two-sided (scipy.stats.fisher_exact).
- Mann & Whitney (1947) U test, two-sided (scipy.stats.mannwhitneyu, tie-corrected).
- Benjamini & Hochberg (1995), J. R. Stat. Soc. B 57:289-300 (step-up FDR adjusted p-values).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from scipy.stats import fisher_exact, mannwhitneyu


def fisher_2x2(k1: int, n1: int, k2: int, n2: int) -> float:
    """Two-sided p of successes k1/n1 vs k2/n2."""
    if n1 <= 0 or n2 <= 0:
        return math.nan
    return float(fisher_exact([[k1, n1 - k1], [k2, n2 - k2]], alternative="two-sided")[1])


def mann_whitney(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) == 0 or len(b) == 0:
        return math.nan
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    if np.ptp(np.concatenate([x, y])) == 0:  # all identical: no evidence of difference
        return 1.0
    p = float(mannwhitneyu(x, y, alternative="two-sided").pvalue)
    return min(1.0, p)


def benjamini_hochberg(pvalues: Sequence[float]) -> list[float]:
    """BH adjusted p-values (q), monotone and capped at 1. NaN stays NaN and is not counted."""
    p = np.asarray(pvalues, dtype=float)
    q = np.full(p.shape, math.nan)
    ok = ~np.isnan(p)
    m = int(ok.sum())
    if m == 0:
        return q.tolist()
    vals = p[ok]
    order = np.argsort(vals, kind="stable")
    ranked = vals[order] * m / np.arange(1, m + 1)
    adj = np.minimum.accumulate(ranked[::-1])[::-1]
    res = np.empty(m)
    res[order] = np.minimum(adj, 1.0)
    q[ok] = res
    return q.tolist()
