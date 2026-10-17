import math

import pytest

from app.stats.significance import benjamini_hochberg, fisher_2x2, mann_whitney


def test_fisher_tea_tasting():
    # Fisher's lady tasting tea: [[3,1],[1,3]] two-sided p = 0.4857
    assert fisher_2x2(3, 4, 1, 4) == pytest.approx(0.4857, abs=1e-4)


def test_fisher_strong_and_null():
    assert fisher_2x2(45, 100, 15, 100) < 1e-5
    assert fisher_2x2(10, 50, 10, 50) == pytest.approx(1.0)
    assert math.isnan(fisher_2x2(1, 0, 1, 5))


def test_mann_whitney():
    assert mann_whitney(list(range(1, 31)), list(range(101, 131))) < 1e-8
    assert mann_whitney([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)
    assert mann_whitney([5.0, 5.0], [5.0, 5.0]) == 1.0
    assert math.isnan(mann_whitney([], [1.0]))


def test_bh_hand_computed():
    p = [0.01, 0.04, 0.03, 0.005]
    # sorted: .005,.01,.03,.04 -> *4/rank = .02,.02,.04,.04 -> monotone
    assert benjamini_hochberg(p) == pytest.approx([0.02, 0.04, 0.04, 0.02])


def test_bh_monotone_capped_nan_safe():
    q = benjamini_hochberg([0.9, 0.8, math.nan, 0.5])
    assert math.isnan(q[2])
    assert all(v <= 1.0 for i, v in enumerate(q) if i != 2)
    assert q[0] == q[1] == q[3] == pytest.approx(0.9)
    assert benjamini_hochberg([]) == []
    assert all(math.isnan(v) for v in benjamini_hochberg([math.nan]))
