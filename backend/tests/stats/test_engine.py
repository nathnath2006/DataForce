import math
from datetime import UTC, date, datetime

from app.domain.enums import Dimension, Metric, StatStatus
from app.domain.schemas import GateConfig
from app.stats.engine import gate_config_from_settings, group_stats, overall, scan
from app.stats.rows import DealRow, value_of
from tests.stats.helpers import make_rows

FIXED = datetime(2026, 1, 1, tzinfo=UTC)
FAST = GateConfig(bootstrap_resamples=400)


def test_row_derivations():
    r = DealRow(
        id=1, won=True, amount=12_000, created_on=date(2025, 1, 1), closed_on=date(2025, 2, 1)
    )
    assert r.cycle_days == 31 and r.amount_band == "10-50k"
    assert DealRow(id=2, won=None, amount=9_999.0).amount_band == "<10k"
    assert DealRow(id=3, won=None, amount=50_000).amount_band == "50k+"
    assert DealRow(id=4, won=None).amount_band is None
    assert (
        DealRow(id=5, won=None, created_on=date(2025, 1, 1), closed_on=date(2025, 2, 1)).cycle_days
        is None
    )
    assert DealRow(id=6, won=True).cycle_days is None
    assert value_of(DealRow(id=7, won=None, region="  "), Dimension.REGION) is None


def test_gate_config_from_settings():
    from app.config import Settings

    cfg = gate_config_from_settings(
        Settings.model_construct(
            stats_confidence=0.9,
            stats_fdr_alpha=0.1,
            gate_min_n=5,
            gate_min_wins=2,
            gate_min_losses=3,
            gate_max_ci_halfwidth_pts=20.0,
            gate_max_ci_rel_halfwidth=0.5,
            stats_bootstrap_resamples=300,
            stats_random_seed=7,
        )
    )
    assert (cfg.confidence, cfg.min_n, cfg.min_losses, cfg.random_seed) == (0.9, 5, 3, 7)


def test_overall_and_group_stats():
    rows = make_rows(1, 300)
    ov = overall(rows, FAST)
    assert ov[Metric.WIN_RATE].n == sum(r.won is not None for r in rows)
    assert ov[Metric.WIN_RATE].status is StatStatus.VERIFIED
    gs = group_stats(rows, Dimension.LEAD_SOURCE, FAST)
    assert [g.group for g in gs] == sorted(g.group for g in gs)
    assert sum(g.n_deals for g in gs) == 300
    ab = group_stats(rows, Dimension.AMOUNT_BAND, FAST)
    assert all(Metric.DEAL_AMOUNT not in g.stats for g in ab)


def test_small_group_not_verified_with_reason():
    rows = make_rows(2, 200) + [DealRow(id=900 + i, won=True, lead_source="tiny") for i in range(6)]
    g = next(g for g in group_stats(rows, Dimension.LEAD_SOURCE, FAST) if g.group == "tiny")
    wr = g.stats[Metric.WIN_RATE]
    assert wr.status is StatStatus.NOT_VERIFIED
    assert any(r.startswith("n = 6") for r in wr.reasons)


def test_missing_handling():
    rows = make_rows(3, 100)
    rows += [DealRow(id=500 + i, won=None, lead_source=None, region="north") for i in range(7)]
    rep = scan(rows, FAST, created_at=FIXED)
    assert rep.missing[Dimension.LEAD_SOURCE.value] == 7
    assert rep.missing["amount"] == 7
    assert all(g.group != "(missing)" for g in rep.groups)
    assert all(f.group != "(missing)" for f in rep.findings)
    assert sum(g.n_deals for g in rep.groups if g.dimension is Dimension.LEAD_SOURCE) == 100
    assert rep.n_deals == 107


def test_scan_structure_and_notes():
    rep = scan(make_rows(4, 200), FAST, created_at=FIXED)
    assert not any(
        f.dimension is Dimension.AMOUNT_BAND and f.metric is Metric.DEAL_AMOUNT
        for f in rep.findings
    )
    assert all(f.q_value is not None and 0 <= f.q_value <= 1 for f in rep.findings if f.p_value)
    assert any("not verified" in n.lower() and "no effect" in n.lower() for n in rep.notes)
    for f in rep.findings:
        assert (f.status is StatStatus.VERIFIED) == (f.reasons == [])


def test_deterministic_json():
    rows = make_rows(5, 150)
    a = scan(rows, FAST, created_at=FIXED).model_dump_json()
    b = scan(list(rows), FAST, created_at=FIXED).model_dump_json()
    assert a == b
    c = scan(rows, GateConfig(bootstrap_resamples=400, random_seed=1), created_at=FIXED)
    assert c.model_dump_json() != a


def test_power_planted_effects_found_and_verified():
    rep = scan(make_rows(11, 1000, planted=True), FAST, created_at=FIXED)
    ver = {
        (f.dimension, f.group, f.metric): f for f in rep.findings if f.status is StatStatus.VERIFIED
    }
    inb = ver[(Dimension.LEAD_SOURCE, "inbound", Metric.WIN_RATE)]
    assert inb.direction == "higher" and inb.diff > 0.2 and inb.diff_ci_low > 0
    out = ver[(Dimension.LEAD_SOURCE, "outbound", Metric.WIN_RATE)]
    assert out.direction == "lower"
    ent = ver[(Dimension.SEGMENT, "enterprise", Metric.CYCLE_DAYS)]
    assert ent.direction == "higher" and ent.diff > 30
    # null dimensions stay clean
    assert not [k for k in ver if k[0] in (Dimension.INDUSTRY, Dimension.REGION, Dimension.OWNER)]


def test_null_false_positive_rate():
    hits = 0
    for seed in range(50):
        rep = scan(
            make_rows(1000 + seed, 200), GateConfig(bootstrap_resamples=300), created_at=FIXED
        )
        hits += any(f.status is StatStatus.VERIFIED for f in rep.findings)
    assert hits / 50 <= 0.10, f"{hits}/50 null datasets had a verified finding"


def test_empty_rows():
    rep = scan([], FAST, created_at=FIXED)
    assert rep.n_deals == 0 and rep.groups == [] and rep.findings == []
    assert rep.overall[Metric.WIN_RATE].value is None
    assert not math.isnan(rep.model_dump()["gates"]["confidence"])


def _row(i, **kw):
    from datetime import date

    base = dict(id=i, won=True, lead_source="a", created_on=date(2026, 1, 1),
                closed_on=date(2026, 2, 1), amount=1000.0)  # fmt: skip
    return DealRow(**{**base, **kw})


def test_validation_duplicates_negative_cycle_bad_amounts():
    from datetime import date

    rows = [_row(1), _row(1, won=False), _row(2, closed_on=date(2025, 12, 1))]
    rows += [_row(3, amount=float("nan")), _row(4, amount=float("inf")), _row(5, amount=-5.0)]
    rep = scan(rows, FAST, created_at=FIXED)
    assert rep.n_deals == 5  # one duplicate dropped
    assert rep.missing["duplicate_deals"] == 1
    assert rep.missing["negative_cycle"] == 1
    assert rep.missing["invalid_amount"] == 3
    assert rep.missing["amount"] == 3
    assert rep.overall[Metric.CYCLE_DAYS].n == 4  # deal 2 excluded from cycle, still a win
    assert rep.overall[Metric.WIN_RATE].n == 5
    assert rep.overall[Metric.DEAL_AMOUNT].n == 2
    assert not any(
        g.group == "<10k" and g.n_deals > 2
        for g in rep.groups
        if g.dimension.value == "amount_band"
    )
    assert sum("duplicate" in n for n in rep.notes) == 1
    assert sum("closed_on before created_on" in n for n in rep.notes) == 1
    assert sum("non-finite" in n for n in rep.notes) == 1
    ov = overall(rows, FAST)  # overall() validates too
    assert ov[Metric.WIN_RATE].n == 5 and ov[Metric.DEAL_AMOUNT].n == 2


def test_finding_applies_ci_width_gate_to_both_sides():
    """A verified finding needs both sides' CI width to pass (reasons 'group:'/'rest:')."""
    cfg = GateConfig(bootstrap_resamples=300, max_ci_halfwidth_pts=2.0)
    rep = scan(make_rows(11, 1000, planted=True), cfg, created_at=FIXED)
    wr = [f for f in rep.findings if f.metric is Metric.WIN_RATE and f.n_group >= 30]
    assert wr and all(any(r.startswith(("group: CI", "rest: CI")) for r in f.reasons) for f in wr)
    assert not [
        f for f in rep.findings if f.status is StatStatus.VERIFIED and f.metric is Metric.WIN_RATE
    ]
    cfg = GateConfig(bootstrap_resamples=300, max_ci_rel_halfwidth=0.001)
    rep = scan(make_rows(11, 1000, planted=True), cfg, created_at=FIXED)
    cyc = [f for f in rep.findings if f.metric is Metric.CYCLE_DAYS and f.n_group >= 30]
    assert cyc and all(any(r.startswith(("group: CI", "rest: CI")) for r in f.reasons) for f in cyc)
