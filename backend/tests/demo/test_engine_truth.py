"""End to end in memory: generator -> stats engine -> check_against_truth (no DB)."""

from __future__ import annotations

import pytest

from app.demo.check import check_against_truth
from app.demo.generator import generate
from app.demo.inmemory import deal_rows
from app.domain.schemas import GateConfig
from app.stats.engine import scan


@pytest.mark.parametrize("seed", [42, 1, 2])
def test_planted_is_found_and_noise_is_not_verified(seed):
    cfg = GateConfig()
    for variant in ("planted", "noise"):
        ds = generate(variant, seed)
        res = check_against_truth(scan(deal_rows(ds), cfg), ds.ground_truth)
        assert res.passed, (variant, seed, res.summary(), res.missed, res.false_positives)


@pytest.mark.parametrize("variant", ["planted", "noise"])
def test_pass_rate_over_20_seeds(variant):
    """FDR 5% means an occasional false positive is expected by design; most seeds must pass."""
    passed = 0
    for seed in range(20):
        ds = generate(variant, seed)
        passed += check_against_truth(scan(deal_rows(ds), GateConfig()), ds.ground_truth).passed
    assert passed >= 18


def test_seed_sweep_calibration():
    """Fixed seeds 1000-1049, 500 bootstrap resamples (deterministic; ~20 s).

    Measured on seeds 1000-1099 (100 per variant, 500 resamples) after the I1-I6 fixes:
    inbound win rate 96%, enterprise cycle 99%, smb cycle 100%, enterprise amount 98%, smb amount
    97%; planted datasets with a false positive (null cells, wrong direction, small group) 0%;
    planted datasets where the check fails (almost all misses) 10%; noise datasets with any
    verified finding 1%. On the 50 seeds below: 48/50, 50, 50, 50, 49 detections, 0 false
    positives, 3 failed checks, 1 noisy dataset. BH bounds the share of false findings, not the
    chance of at least one, hence the margins.
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
    assert len(det) == 5 and all(v >= 44 for v in det.values()), det  # >= 88% each
    assert fp <= 3, fp
    assert fail <= 8, fail
    assert noisy <= 4, noisy


@pytest.mark.parametrize("seed", [1121, 1219])
def test_noise_seeds_that_used_to_crash_the_generator(seed):
    ds = generate("noise", seed)
    assert all((d.closed_on - d.created_on).days <= 730 for d in ds.deals if d.closed_on)
