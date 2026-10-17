from __future__ import annotations

import math
from collections import Counter, defaultdict
from statistics import median

import pytest
from scipy import stats

from app.demo.generator import generate
from app.domain.enums import DealStage, LeadSource, Segment

SEEDS = [42, 7, 123]


def _closed(ds):
    return [d for d in ds.deals if d.stage in (DealStage.CLOSED_WON, DealStage.CLOSED_LOST)]


def _seg(ds):
    acc = {a.key: a for a in ds.accounts}
    return lambda d: acc[d.account_key].segment


def test_deterministic_and_seed_sensitive():
    a, b = generate("planted", 42), generate("planted", 42)
    assert a.model_dump_json() == b.model_dump_json()
    assert generate("planted", 43).model_dump_json() != a.model_dump_json()
    assert generate("noise", 42).model_dump_json() != a.model_dump_json()


def test_scale_and_ground_truth_filled():
    ds = generate("planted", 42)
    assert len(ds.deals) == 200 and len(ds.users) == 6
    assert 60 <= len(ds.accounts) <= 80
    gt = ds.ground_truth
    assert (
        gt.n_deals == 200
        and gt.n_accounts == len(ds.accounts)
        and gt.n_contacts == len(ds.contacts)
    )
    assert gt.planted and gt.small_groups == [("lead_source", "referral")]
    assert {str(x) for x in gt.null_dimensions} == {"industry", "region", "owner"}
    noise = generate("noise", 42).ground_truth
    assert noise.planted == [] and len(noise.null_dimensions) == 6 and noise.small_groups == []
    assert len(generate("planted", 1, n_deals=60).deals) == 60


@pytest.mark.parametrize("seed", SEEDS)
def test_mix_and_closed_share(seed):
    ds = generate("planted", seed)
    leads = Counter(d.lead_source for d in ds.deals)
    assert 0.28 <= leads[LeadSource.INBOUND] / 200 <= 0.35  # 35% minus ~8% masked
    segs = Counter(_seg(ds)(d) for d in ds.deals)
    assert (
        segs[Segment.SMB] == 80 and segs[Segment.MIDMARKET] == 70 and segs[Segment.ENTERPRISE] == 50
    )
    assert 0.72 <= len(_closed(ds)) / 200 <= 0.88


@pytest.mark.parametrize("variant", ["planted", "noise"])
def test_org_charts_are_trees(variant):
    ds = generate(variant, 42)
    by_acc = defaultdict(list)
    for c in ds.contacts:
        by_acc[c.account_key].append(c)
    assert set(by_acc) == {a.key for a in ds.accounts}
    for contacts in by_acc.values():
        assert 4 <= len(contacts) <= 9
        keys = {c.key for c in contacts}
        roots = [c for c in contacts if c.reports_to_key is None]
        assert len(roots) == 1
        parent = {c.key: c.reports_to_key for c in contacts}
        assert all(p in keys for p in parent.values() if p)
        for k in keys:  # every node reaches the root without a cycle
            seen, cur = set(), k
            while parent[cur]:
                assert cur not in seen
                seen.add(cur)
                cur = parent[cur]
            assert cur == roots[0].key


def test_titles_missing_rates_and_names():
    ds = generate("planted", 42)
    titles = [c.title for c in ds.contacts]
    assert 0.02 <= titles.count(None) / len(titles) <= 0.09
    joined = " ".join(t for t in titles if t).lower()
    assert "directeur" in joined and "head of sales" in joined and "resp." in joined
    assert any(t and t.isupper() for t in titles)
    assert len({c.full_name for c in ds.contacts}) == len(ds.contacts)  # invented and unique
    deals = ds.deals
    rate = lambda f: sum(f(d) for d in deals) / len(deals)  # noqa: E731
    assert 0.03 <= rate(lambda d: d.lead_source is None) <= 0.14
    assert 0.01 <= rate(lambda d: d.amount_eur is None) <= 0.10
    closed = _closed(ds)
    assert 0 < sum(d.closed_on is None for d in closed) / len(closed) <= 0.08
    assert any(a.industry is None for a in ds.accounts) and any(
        a.region is None for a in ds.accounts
    )
    assert all(a.domain.endswith(".example") for a in ds.accounts)


def test_notes_and_comments():
    ds = generate("planted", 42)
    assert 38 <= len(ds.notes) <= 50 and 18 <= len(ds.comments) <= 25
    keys = {n.key for n in ds.notes}
    corr = [n for n in ds.notes if n.corrects_key]
    assert corr and all(n.corrects_key in keys for n in corr)
    assert any(c.corrects_key for c in ds.comments)


def test_planted_effects_realised_seed_42_and_power():
    ds = generate("planted", 42)
    closed, seg = _closed(ds), _seg(ds)
    won = lambda d: d.stage == DealStage.CLOSED_WON  # noqa: E731

    # lead source -> win rate: inbound vs rest, with the default gates
    inb = [d for d in closed if d.lead_source == LeadSource.INBOUND]
    rest = [d for d in closed if d.lead_source and d.lead_source != LeadSource.INBOUND]
    k1, n1 = sum(map(won, inb)), len(inb)
    k2, n2 = sum(map(won, rest)), len(rest)
    assert n1 >= 30 and k1 >= 10 and n1 - k1 >= 10
    p1, p2 = k1 / n1, k2 / n2
    assert p1 - p2 > 0.2
    half = 1.96 * math.sqrt(p1 * (1 - p1) / n1)
    assert half <= 0.15
    assert (
        stats.fisher_exact([[k1, n1 - k1], [k2, n2 - k2]])[1] < 5e-3
    )  # BH over ~100 tests is safe

    # small group: referral stays under the min-n gate, with a high observed win rate
    ref = [d for d in closed if d.lead_source == LeadSource.REFERRAL]
    assert 10 <= len(ref) < 30
    assert sum(map(won, ref)) / len(ref) > 0.5

    # segment -> cycle and amount: every group has n >= 30 and medians in the planted order
    cyc, amt = {}, {}
    for s in Segment:
        grp = [d for d in closed if seg(d) == s and d.closed_on]
        cyc[s] = [(d.closed_on - d.created_on).days for d in grp]
        amt[s] = [float(d.amount_eur) for d in ds.deals if seg(d) == s and d.amount_eur is not None]
        assert len(cyc[s]) >= 30 and len(amt[s]) >= 30
    assert median(cyc[Segment.ENTERPRISE]) > 85
    assert 45 < median(cyc[Segment.MIDMARKET]) < 80
    assert median(cyc[Segment.SMB]) < 40
    assert median(amt[Segment.ENTERPRISE]) > 40_000
    assert median(amt[Segment.SMB]) < 12_000
    # median CI relative half-width (log-normal sigma s, n): ~1.25 * 1.96 * s / sqrt(n) < 30%
    assert 1.25 * 1.96 * 0.35 / math.sqrt(len(cyc[Segment.ENTERPRISE])) < 0.30
    assert 1.25 * 1.96 * 0.5 / math.sqrt(len(amt[Segment.ENTERPRISE])) < 0.30
    for a, b in [(Segment.ENTERPRISE, Segment.SMB), (Segment.MIDMARKET, Segment.SMB)]:
        assert stats.mannwhitneyu(cyc[a], cyc[b]).pvalue < 1e-6
    assert stats.mannwhitneyu(amt[Segment.ENTERPRISE], amt[Segment.SMB]).pvalue < 1e-6


@pytest.mark.parametrize("seed", SEEDS)
def test_referral_always_small_and_inbound_always_large(seed):
    ds = generate("planted", seed)
    closed = _closed(ds)
    assert sum(d.lead_source == LeadSource.REFERRAL for d in closed) < 30
    assert sum(d.lead_source == LeadSource.INBOUND for d in closed) >= 30


def test_noise_variant_is_independent_of_dimensions():
    ds = generate("noise", 42, n_deals=1000)  # larger n so the chi-square has power to fail
    seg = _seg(ds)
    closed = _closed(ds)
    acc = {a.key: a for a in ds.accounts}
    rows = [
        (
            d.lead_source,
            seg(d),
            acc[d.account_key].industry,
            acc[d.account_key].region,
            d.owner_key,
            d,
        )
        for d in closed
    ]
    for idx in range(5):
        cats = sorted({str(r[idx]) for r in rows})
        table = [
            [
                sum(
                    1
                    for r in rows
                    if str(r[idx]) == c and (r[5].stage == DealStage.CLOSED_WON) == w
                )
                for w in (True, False)
            ]
            for c in cats
        ]
        table = [t for t in table if sum(t) > 0]
        assert stats.chi2_contingency(table).pvalue > 0.01
    # cycle / amount: segment has no effect
    by = defaultdict(list)
    for d in ds.deals:
        if d.amount_eur is not None:
            by[seg(d)].append(float(d.amount_eur))
    assert stats.kruskal(*by.values()).pvalue > 0.01


@pytest.mark.parametrize("n", [49, 20_001, 0, -5])
def test_n_deals_bounds(n):
    with pytest.raises(ValueError):
        generate("planted", 1, n_deals=n)


def test_owner_is_balanced_within_segment():
    ds = generate("planted", 7, n_deals=240)
    acc = {a.key: a.segment for a in ds.accounts}
    for seg in set(acc.values()):
        counts = {}
        for d in ds.deals:
            if acc[d.account_key] == seg:
                counts[d.owner_key] = counts.get(d.owner_key, 0) + 1
        assert max(counts.values()) - min(counts.values()) <= 6, (seg, counts)
