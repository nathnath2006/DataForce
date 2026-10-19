"""Confidence intervals. Every function returns (estimate, low, high).

References:
- Wilson, E.B. (1927), J. Am. Stat. Assoc. 22:209-212 (score interval for a proportion).
- Newcombe, R.G. (1998), "Interval estimation for the difference between independent
  proportions: comparison of eleven methods", Stat. Med. 17:873-890; method 10 (hybrid score).
- Efron & Tibshirani (1993), "An Introduction to the Bootstrap" (percentile bootstrap).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from scipy.stats import norm

Interval = tuple[float, float, float]
_NAN: Interval = (math.nan, math.nan, math.nan)
_CHUNK_CELLS = 4_000_000


def _z(conf: float) -> float:
    return float(norm.ppf(1 - (1 - conf) / 2))


def wilson(k: int, n: int, conf: float = 0.95) -> Interval:
    if n <= 0:
        return _NAN
    z = _z(conf)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    # The Wilson interval always contains p; clamping to p removes float noise such as a
    # lower bound of 5.6e-17 for k = 0, which would put the estimate outside its own CI.
    return p, min(p, max(0.0, centre - half)), max(p, min(1.0, centre + half))


def newcombe_diff(k1: int, n1: int, k2: int, n2: int, conf: float = 0.95) -> Interval:
    """Hybrid score interval for p1 - p2 (Newcombe 1998, method 10)."""
    if n1 <= 0 or n2 <= 0:
        return _NAN
    p1, l1, u1 = wilson(k1, n1, conf)
    p2, l2, u2 = wilson(k2, n2, conf)
    d = p1 - p2
    low = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    high = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return d, max(-1.0, low), min(1.0, high)


def _boot_medians(values: np.ndarray, resamples: int, rng: np.random.Generator) -> np.ndarray:
    n = values.size
    out = np.empty(resamples)
    step = max(1, _CHUNK_CELLS // n)
    for start in range(0, resamples, step):
        m = min(step, resamples - start)
        idx = rng.integers(0, n, size=(m, n))
        out[start : start + m] = np.median(values[idx], axis=1)
    return out


def percentile_interval(boot: np.ndarray, conf: float) -> tuple[float, float]:
    a = (1 - conf) / 2
    lo, hi = np.quantile(boot, [a, 1 - a])
    return float(lo), float(hi)


def bootstrap_median(
    values: Sequence[float], conf: float, resamples: int, rng: np.random.Generator
) -> Interval:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return _NAN
    lo, hi = percentile_interval(_boot_medians(arr, resamples, rng), conf)
    return float(np.median(arr)), lo, hi


def bootstrap_median_diff(
    a: Sequence[float],
    b: Sequence[float],
    conf: float,
    resamples: int,
    rng: np.random.Generator,
) -> Interval:
    """Percentile bootstrap CI of median(a) - median(b); a and b resampled independently."""
    x = np.asarray(a, dtype=float)
    y = np.asarray(b, dtype=float)
    if x.size == 0 or y.size == 0:
        return _NAN
    boot = _boot_medians(x, resamples, rng) - _boot_medians(y, resamples, rng)
    lo, hi = percentile_interval(boot, conf)
    return float(np.median(x) - np.median(y)), lo, hi
