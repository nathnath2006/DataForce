from __future__ import annotations

from datetime import UTC, datetime

from app.demo.check import check_against_truth
from app.demo.generator import generate
from app.domain.enums import Dimension, Metric, StatStatus
from app.domain.schemas import EffectFinding, GateConfig, ScanReport

TRUTH = generate("planted", 42).ground_truth
NOISE = generate("noise", 42).ground_truth


def _f(dim, group, metric, direction="higher", status=StatStatus.VERIFIED):
    return EffectFinding(
        dimension=dim, group=group, metric=metric, group_value=1, rest_value=0, diff=1,
        diff_ci_low=0.5, diff_ci_high=1.5, p_value=0.001, q_value=0.01, test="t", n_group=50,
        n_rest=100, direction=direction, status=status,
    )  # fmt: skip


def _report(findings):
    return ScanReport(
        workspace_id=None, created_at=datetime.now(UTC), n_deals=200, n_closed=160, n_open=40,
        gates=GateConfig(), overall={}, groups=[], findings=findings,
    )  # fmt: skip


def _planted_findings():
    return [
        _f(Dimension.LEAD_SOURCE, "inbound", Metric.WIN_RATE),
        _f(Dimension.SEGMENT, "enterprise", Metric.CYCLE_DAYS),
        _f(Dimension.SEGMENT, "smb", Metric.CYCLE_DAYS, "lower"),
        _f(Dimension.SEGMENT, "enterprise", Metric.DEAL_AMOUNT),
        _f(Dimension.SEGMENT, "smb", Metric.DEAL_AMOUNT, "lower"),
    ]


def test_all_found_passes_and_mirror_finding_is_not_a_false_positive():
    fs = _planted_findings() + [_f(Dimension.LEAD_SOURCE, "outbound", Metric.WIN_RATE, "lower")]
    res = check_against_truth(_report(fs), TRUTH)
    assert res.passed and not res.missed and not res.false_positives and res.small_groups_ok
    assert len(res.found) == len(TRUTH.planted)


def test_missing_or_unverified_effect_fails():
    fs = _planted_findings()[1:]
    res = check_against_truth(_report(fs), TRUTH)
    assert not res.passed and [m.group for m in res.missed] == ["inbound"]
    fs = _planted_findings()
    fs[0] = _f(Dimension.LEAD_SOURCE, "inbound", Metric.WIN_RATE, status=StatStatus.NOT_VERIFIED)
    assert not check_against_truth(_report(fs), TRUTH).passed
    fs = _planted_findings()
    fs[0] = _f(Dimension.LEAD_SOURCE, "inbound", Metric.WIN_RATE, "lower")  # wrong direction
    assert not check_against_truth(_report(fs), TRUTH).passed


def test_small_group_verified_fails_but_not_verified_is_fine():
    ok = _planted_findings() + [
        _f(Dimension.LEAD_SOURCE, "referral", Metric.WIN_RATE, status=StatStatus.NOT_VERIFIED)
    ]
    assert check_against_truth(_report(ok), TRUTH).passed
    bad = _planted_findings() + [_f(Dimension.LEAD_SOURCE, "referral", Metric.WIN_RATE)]
    res = check_against_truth(_report(bad), TRUTH)
    assert not res.passed and not res.small_groups_ok


def test_null_dimension_verified_is_false_positive():
    fs = _planted_findings() + [_f(Dimension.OWNER, "rep1", Metric.WIN_RATE)]
    res = check_against_truth(_report(fs), TRUTH)
    assert not res.passed and len(res.false_positives) == 1


def test_noise_variant():
    assert check_against_truth(_report([]), NOISE).passed
    nv = [_f(Dimension.SEGMENT, "smb", Metric.DEAL_AMOUNT, status=StatStatus.NOT_VERIFIED)]
    assert check_against_truth(_report(nv), NOISE).passed
    res = check_against_truth(_report([_f(Dimension.SEGMENT, "smb", Metric.DEAL_AMOUNT)]), NOISE)
    assert not res.passed and len(res.false_positives) == 1


def test_null_cells_filled_both_variants():
    assert (Dimension.SEGMENT, Metric.WIN_RATE) in TRUTH.null_cells
    assert (Dimension.AMOUNT_BAND, Metric.WIN_RATE) in TRUTH.null_cells
    assert (Dimension.LEAD_SOURCE, Metric.CYCLE_DAYS) in TRUTH.null_cells
    assert (Dimension.OWNER, Metric.DEAL_AMOUNT) in TRUTH.null_cells
    assert (Dimension.AMOUNT_BAND, Metric.CYCLE_DAYS) not in TRUTH.null_cells  # leaks via segment
    assert len(NOISE.null_cells) == len(Dimension) * len(Metric)


def test_null_cell_false_positive_even_in_a_non_null_dimension():
    for dim, m in [
        (Dimension.SEGMENT, Metric.WIN_RATE),
        (Dimension.LEAD_SOURCE, Metric.DEAL_AMOUNT),
        (Dimension.AMOUNT_BAND, Metric.WIN_RATE),
    ]:
        res = check_against_truth(_report(_planted_findings() + [_f(dim, "x", m)]), TRUTH)
        assert not res.passed and len(res.false_positives) == 1


def test_other_real_is_listed_not_dropped():
    fs = _planted_findings() + [
        _f(Dimension.LEAD_SOURCE, "outbound", Metric.WIN_RATE, "lower"),
        _f(Dimension.AMOUNT_BAND, "<10k", Metric.CYCLE_DAYS, "lower"),
    ]
    res = check_against_truth(_report(fs), TRUTH)
    assert res.passed and not res.false_positives
    assert {(f.dimension, f.group) for f in res.other_real} == {
        (Dimension.LEAD_SOURCE, "outbound"),
        (Dimension.AMOUNT_BAND, "<10k"),
    }
