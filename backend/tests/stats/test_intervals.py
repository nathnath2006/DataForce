import math

import numpy as np
import pytest

from app.stats.intervals import bootstrap_median, bootstrap_median_diff, newcombe_diff, wilson


# Newcombe (1998), Table I: Wilson intervals for single proportions.
@pytest.mark.parametrize(
    ("k", "n", "low", "high"),
    [
        (81, 263, 0.2553, 0.3662),
        (15, 148, 0.0624, 0.1605),
        (0, 20, 0.0, 0.1611),
        (1, 29, 0.0061, 0.1718),
    ],
)
def test_wilson_paper_values(k, n, low, high):
    _, lo, hi = wilson(k, n)
    assert lo == pytest.approx(low, abs=6e-4)
    assert hi == pytest.approx(high, abs=6e-4)


def test_wilson_edges():
    assert all(math.isnan(x) for x in wilson(0, 0))
    p, lo, hi = wilson(10, 10)
    assert p == 1.0 and hi <= 1.0 and lo < 1.0


# Newcombe (1998), method 10: 56/70 vs 48/80 -> 0.0524 to 0.3339.
def test_newcombe_paper_example():
    d, lo, hi = newcombe_diff(56, 70, 48, 80)
    assert d == pytest.approx(0.2)
    assert lo == pytest.approx(0.0524, abs=5e-5)
    assert hi == pytest.approx(0.3339, abs=5e-5)


def test_newcombe_other_examples():
    _, lo, hi = newcombe_diff(9, 10, 3, 10)
    assert (lo, hi) == (pytest.approx(0.1705, abs=1e-4), pytest.approx(0.8090, abs=1e-4))
    _, lo, hi = newcombe_diff(0, 10, 0, 20)
    assert lo < 0 < hi
    # antisymmetry
    d1 = newcombe_diff(30, 100, 20, 90)
    d2 = newcombe_diff(20, 90, 30, 100)
    assert d1[1] == pytest.approx(-d2[2]) and d1[2] == pytest.approx(-d2[1])


def test_bootstrap_median_deterministic_and_sensible():
    x = np.random.default_rng(0).normal(100, 10, 200)
    a = bootstrap_median(x, 0.95, 1000, np.random.default_rng(1))
    b = bootstrap_median(x, 0.95, 1000, np.random.default_rng(1))
    assert a == b
    est, lo, hi = a
    assert est == pytest.approx(float(np.median(x)))
    assert lo < est < hi and hi - lo < 8


def test_bootstrap_median_diff_detects_shift():
    rng = np.random.default_rng(3)
    a = rng.normal(120, 10, 100)
    b = rng.normal(100, 10, 100)
    d, lo, hi = bootstrap_median_diff(a, b, 0.95, 1000, np.random.default_rng(2))
    assert 15 < d < 25 and lo > 0
    d, lo, hi = bootstrap_median_diff(
        b, rng.normal(100, 10, 100), 0.95, 1000, np.random.default_rng(2)
    )
    assert lo < 0 < hi


def test_bootstrap_empty():
    assert all(math.isnan(v) for v in bootstrap_median([], 0.95, 200, np.random.default_rng(0)))


def test_wilson_contains_its_estimate_exactly_at_the_edges():
    # k = 0 used to give a lower bound of 5.6e-17 > 0 = the estimate (seed-42 "partner" group).
    for n in range(1, 400):
        for k in (0, 1, n - 1, n):
            p, low, high = wilson(k, n)
            assert low <= p <= high
        assert wilson(0, n)[1] == 0.0
        assert wilson(n, n)[2] == 1.0
