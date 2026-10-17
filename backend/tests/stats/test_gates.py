import pytest
from pydantic import ValidationError

from app.domain.enums import Metric
from app.domain.schemas import GateConfig
from app.stats import gates
from app.stats.gates import gate_finding, gate_median, gate_rate

CFG = GateConfig()


def test_rate_n_boundary():
    assert gate_rate(15, 30, 0.35, 0.65, CFG) == []
    r = gate_rate(14, 29, 0.35, 0.65, CFG)
    assert r == ["n = 29 < 30"]


def test_rate_wins_losses_boundary():
    assert gate_rate(10, 40, 0.15, 0.37, CFG) == []
    assert gate_rate(9, 40, 0.15, 0.37, CFG) == ["only 9 wins (< 10)"]
    assert gate_rate(31, 40, 0.65, 0.88, CFG) == ["only 9 losses (< 10)"]


def test_rate_ci_width():
    r = gate_rate(15, 30, 0.2, 0.8, CFG)
    assert r == ["CI ±30.0 pts > ±15 pts"]
    assert gate_rate(15, 30, 0.35, 0.65, CFG) == []  # exactly ±15.0 passes


def test_median_gates():
    assert gate_median(30, 100.0, 80.0, 120.0, CFG) == []
    assert gate_median(29, 100.0, 80.0, 120.0, CFG) == ["n = 29 < 30"]
    r = gate_median(30, 100.0, 60.0, 140.0, CFG)
    assert len(r) == 1 and "40%" in r[0]


def test_finding_gate():
    ok = gate_finding(Metric.WIN_RATE, 30, 10, 100, 40, 0.01, 0.1, 0.3, CFG)
    assert ok == []
    r = gate_finding(Metric.WIN_RATE, 29, 9, 100, 40, 0.06, -0.1, 0.3, CFG)
    assert len(r) == 4
    assert any("q = 0.06" in x for x in r) and any("includes 0" in x for x in r)
    # wins gate does not apply to medians
    assert gate_finding(Metric.CYCLE_DAYS, 30, None, 30, None, 0.001, 5.0, 9.0, CFG) == []


def test_non_finite_fails_closed_and_missing_wins():
    import math

    cfg = GateConfig()
    inf = math.inf
    assert gates.gate_median(40, inf, 1.0, inf, cfg)
    assert gates.gate_median(40, 5.0, -inf, 6.0, cfg)
    assert gates.gate_rate(40, 100, inf, 0.9, cfg)
    assert gates.gate_finding(Metric.CYCLE_DAYS, 40, None, 40, None, math.inf, 1.0, 2.0, cfg)
    assert gates.gate_finding(Metric.CYCLE_DAYS, 40, None, 40, None, 0.01, -inf, inf, cfg)
    assert any(
        "unknown" in r
        for r in gates.gate_finding(Metric.WIN_RATE, 40, None, 40, 20, 0.01, 0.1, 0.2, cfg)
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_ci_halfwidth_pts", float("nan")),
        ("max_ci_halfwidth_pts", float("inf")),
        ("max_ci_rel_halfwidth", float("nan")),
        ("fdr_alpha", float("nan")),
        ("confidence", 1.0),
        ("min_n", 0),
    ],
)
def test_gate_config_refuses_values_that_would_open_every_gate(field, value):
    # SR5-06: a NaN threshold made every comparison False, so every gate passed.
    with pytest.raises(ValidationError):
        GateConfig(**{field: value})


def test_difference_ci_reasons_use_readable_units():
    amount = gate_finding(Metric.DEAL_AMOUNT, 40, None, 40, None, 0.5, -190.0, 9921.4, CFG)
    assert "difference CI [-190, +9,921] EUR includes 0" in amount
    days = gate_finding(Metric.CYCLE_DAYS, 40, None, 40, None, 0.5, -3.46, 2.0, CFG)
    assert "difference CI [-3.5, +2.0] days includes 0" in days
