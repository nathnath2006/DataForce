"""End to end in memory: generator -> stats engine -> check_against_truth (no DB)."""

from __future__ import annotations

import pytest

from app.demo.check import check_against_truth
from app.demo.generator import generate
from app.demo.inmemory import deal_rows
from app.domain.schemas import GateConfig
from app.stats.engine import scan


@pytest.mark.parametrize("seed", [42, 1, 2])
def test_planted_is_found(seed):
    ds = generate("planted", seed)
    res = check_against_truth(scan(deal_rows(ds), GateConfig()), ds.ground_truth)
    assert res.passed, (seed, res.summary(), res.missed, res.false_positives)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_noise_is_not_verified(seed):
    # Noise seed 42 (the dev-database demo) is one of the ~4% of noise datasets where the engine
    # does show a spurious verified finding (owner rep4 x cycle, q = 0.028). Not asserted away:
    # see test_seed_42_noise_is_a_known_false_alarm.
    ds = generate("noise", seed)
    res = check_against_truth(scan(deal_rows(ds), GateConfig()), ds.ground_truth)
    assert res.passed, (seed, res.summary(), res.false_positives)


def test_seed_42_noise_is_a_known_false_alarm():
    ds = generate("noise", 42)
    res = check_against_truth(scan(deal_rows(ds), GateConfig()), ds.ground_truth)
    assert [(str(f.dimension), f.group, str(f.metric)) for f in res.false_positives] == [
        ("owner", "rep4", "cycle_days")
    ]


@pytest.mark.parametrize("variant", ["planted", "noise"])
def test_pass_rate_over_20_seeds(variant):
    """FDR 5% means an occasional false positive is expected by design; most seeds must pass."""
    passed = 0
    for seed in range(20):
        ds = generate(variant, seed)
        passed += check_against_truth(scan(deal_rows(ds), GateConfig()), ds.ground_truth).passed
    assert passed >= 18


def test_seed_sweep_calibration():
    """Fixed seeds 1000-1049, 500 bootstrap resamples, 350 deals (deterministic; ~90 s).

    Measured on seeds 1000-1099 (100 per variant, 500 resamples) at 350 deals: every planted
    effect detected in 100% of datasets; planted datasets with a false positive (null cell, wrong
    direction, small group) 8%; planted datasets where the check fails 8% (all of them false
    positives, none a miss); noise datasets with any verified finding 4%. On the 50 seeds below:
    all 5 effects detected 50/50, 4 datasets with a false positive and 4 failed checks, 2 noisy
    noise datasets. BH bounds the share of false findings, not the chance of at least one, and
    more power means more verified findings per scan, hence the margins. (Previously, at 200
    deals: detection 93-100%, false positives 0-1%, failed checks 8-10%, noisy 1%.)
    """
    cfg = GateConfig(bootstrap_resamples=500)
    seeds = range(1000, 1050)
    det: dict[tuple, int] = {}
    fp = fail = noisy = 0
    for seed in seeds:
        ds = generate("planted", seed)
        res = check_against_truth(scan(deal_rows(ds), cfg), ds.ground_truth)
        for e in res.found:
            det[(e.dimension, e.group, e.metric)] = det.get((e.dimension, e.group, e.metric), 0) + 1
        fp += bool(res.false_positives)
        fail += not res.passed
        nds = generate("noise", seed)
        rep = scan(deal_rows(nds), cfg)
        noisy += any(f.status == "verified" for f in rep.findings)
    assert len(det) == 5 and all(v >= 48 for v in det.values()), det  # >= 96% each
    assert fp <= 8, fp
    assert fail <= 8, fail
    assert noisy <= 6, noisy


@pytest.mark.parametrize("seed", [1121, 1219])
def test_noise_seeds_that_used_to_crash_the_generator(seed):
    ds = generate("noise", seed)
    assert all((d.closed_on - d.created_on).days <= 730 for d in ds.deals if d.closed_on)
