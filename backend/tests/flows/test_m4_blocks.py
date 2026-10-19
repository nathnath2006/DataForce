"""Deal velocity, engagement score and rep touchpoint ratio (hand-computed expectations)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.flows.engine import run_graph
from app.flows.memory import MemoryLoader
from app.flows.ports import FlowLimits
from tests.flows.helpers import FAST, ds, graph

TODAY = date(2026, 4, 1)


def go(table: str, df: pd.DataFrame, cfg: dict):
    g = graph([("d", ds(table)), ("b", cfg)], [("d", "out", "b", "in")])
    cap: dict = {}
    r = run_graph(g, MemoryLoader({table: df}), FAST, FlowLimits(), "b", capture=cap, today=TODAY)[
        "b"
    ]
    return r, cap.get("b")


def _events(durations: dict[str, list[tuple[str, float]]], open_stay=None):
    rows = []
    for deal, stays in durations.items():
        at = pd.Timestamp("2025-01-01")
        for stage, days in stays:
            rows.append({"deal_id": deal, "to_stage": stage, "changed_at": at})
            at = at + pd.Timedelta(days=days)
        rows.append({"deal_id": deal, "to_stage": "closed_won", "changed_at": at})
    for deal, (stage, start) in (open_stay or {}).items():
        rows.append({"deal_id": deal, "to_stage": stage, "changed_at": pd.Timestamp(start)})
    return pd.DataFrame(rows)


def test_velocity_percentile_flags_and_min_n():
    # 40 deals in "qual" with 1..40 days: percentiles (k - 0.5) / 40; "rare" has only 5 stays
    d = {f"d{k}": [("qual", float(k))] for k in range(1, 41)}
    d.update({f"r{k}": [("rare", float(k))] for k in range(5)})
    r, out = go("stage_events", _events(d), {"type": "velocity"})
    assert r.status == "ok", r.error
    by = out.set_index("deal_id")
    assert by.loc["d1", "velocity_percentile"] == pytest.approx(0.5 / 40)
    assert by.loc["d1", "velocity_flag"] == "fast_track"
    assert by.loc["d40", "velocity_flag"] == "stagnant"
    assert by.loc["d20", "velocity_flag"] == "normal"
    # quartiles of 40 deals: 10 fast, 10 stagnant (percentile <= .25 / >= .75)
    assert r.view.counts == {"fast_track": 10, "normal": 20, "stagnant": 10, "no_flag": 5}
    props = {b.stage: b for b in r.view.benchmarks}
    assert props["qual"].sufficient and props["qual"].n == 40
    assert not props["rare"].sufficient  # insufficient data: its deals get no flag, with a reason
    assert (
        pd.isna(by.loc["r1", "velocity_flag"]) and "at least 30" in by.loc["r1", "velocity_reason"]
    )
    # a higher min_stage_n leaves every deal without a flag, with a reason
    r2, o2 = go("stage_events", _events(d), {"type": "velocity", "min_stage_n": 50})
    assert o2["velocity_flag"].isna().all()
    assert o2["velocity_reason"].str.contains("at least 50").all()


def test_velocity_identical_deals_get_no_flags():
    # review #3: a sum-of-medians index called 47% of null deals stagnant
    rng = np.random.default_rng(5)
    d = {
        f"d{k}": [(s, float(x)) for s, x in zip("abc", rng.lognormal(3, 0.9, 3), strict=True)]
        for k in range(300)
    }
    r, _ = go("stage_events", _events(d), {"type": "velocity"})
    c = r.view.counts
    # the median of three percentiles is narrower than a uniform: about 31% flagged by construction
    # in this null (the sum-of-medians index flagged 68%, 47% of them stagnant)
    assert c["stagnant"] + c["fast_track"] <= 0.36 * 300
    assert c["stagnant"] <= 0.2 * 300
    ident = {f"d{k}": [("a", 10.0), ("b", 20.0)] for k in range(40)}
    r2, _ = go("stage_events", _events(ident), {"type": "velocity"})
    assert r2.view.counts["normal"] == 40


def test_velocity_open_stays_reported_apart():
    d = {f"d{k}": [("qual", float(k))] for k in range(1, 41)}  # p75 of 1..40 = 30.25
    ev = _events(d, open_stay={"slow": ("qual", "2026-01-01"), "new": ("qual", "2026-03-25")})
    r, out = go("stage_events", ev, {"type": "velocity"})
    by = out.set_index("deal_id")
    assert by.loc["slow", "stalled_in_stage"] and by.loc["slow", "open_days"] == 90
    assert not by.loc["new", "stalled_in_stage"]
    assert pd.isna(by.loc["slow", "velocity_flag"])
    assert "no completed stay" in by.loc["slow", "velocity_reason"]
    assert r.view.n_stalled == 1
    # open stays never enter the benchmark
    assert {b.stage: b.n for b in r.view.benchmarks}["qual"] == 40


def test_engagement_components_window_and_penalty():
    def a(acc, kind, at):
        return {"account_id": acc, "kind": kind, "occurred_at": pd.Timestamp(at)}

    df = pd.DataFrame(
        [
            a("A", "meeting", "2026-03-25"),  # 7 days ago: 3
            a("A", "call", "2026-03-01"),  # 31 days ago: 2
            a("A", "email", "2026-01-15"),  # 76 days: 1
            a("A", "email", "2025-12-01"),  # outside the 90-day window
            a("B", "call", "2026-02-20"),  # 40 days ago: 2, quiet > 30 -> halved
            a("B", "chat", "2026-03-30"),  # other: 1 (recent, so no penalty)
            a("C", "meeting", "2025-10-01"),  # outside the window, no score, penalised
            a("A", "meeting", "2026-05-01"),  # in the future: ignored
        ]
    )
    r, out = go("activities", df, {"type": "engagement"})
    assert r.status == "ok", r.error
    by = out.set_index("account_id")
    assert by.loc["A", "raw_score"] == 6 and by.loc["A", "engagement_score"] == 6
    assert (
        by.loc["A", "n_meeting"] == 1 and by.loc["A", "n_call"] == 1 and by.loc["A", "n_email"] == 1
    )
    assert by.loc["B", "raw_score"] == 3 and by.loc["B", "days_since_last"] == 2
    assert not by.loc["B", "penalty_applied"] and by.loc["B", "engagement_score"] == 3
    assert by.loc["C", "raw_score"] == 0 and by.loc["C", "penalty_applied"]
    assert any("after the run date" in w for w in r.warnings)
    # only the 40-day-old call: penalty halves 2 to 1
    r2, o2 = go("activities", df[df["account_id"] == "B"].head(1), {"type": "engagement"})
    row = o2.iloc[0]
    assert row["penalty_applied"] and row["engagement_score"] == 1.0 and row["raw_score"] == 2
    assert r.view.n_accounts == 3 and r.view.n_penalised == 1


def test_touchpoint_ratio_zero_outreach_is_null():
    df = pd.DataFrame(
        {
            "author": ["x", "x", "x", "x", "x", "y", "y", None],
            "kind": ["meeting", "meeting", "call", "email", "call", "meeting", "call", "email"],
            "direction": [None, None, "outbound", "outbound", "inbound", None, "inbound", None],
        }
    )
    r, out = go("activities", df, {"type": "touchpoint", "min_outreach": 1})
    by = out.set_index("author")
    assert by.loc["x", "meetings"] == 2 and by.loc["x", "outreach"] == 2
    assert by.loc["x", "touchpoint_ratio"] == 3.0  # 2 x 3 / 2
    assert by.loc["y", "outreach"] == 0 and pd.isna(by.loc["y", "touchpoint_ratio"])
    assert any("no outreach" in w for w in r.warnings)
    assert r.view.n_no_outreach == 1


def test_touchpoint_minimum_outreach_gives_null_with_reason():
    # 1 email + 1 meeting used to give 3.0 with no uncertainty (review #5)
    df = pd.DataFrame(
        {"author": ["x", "x"], "kind": ["email", "meeting"], "direction": ["outbound", None]}
    )
    r, out = go("activities", df, {"type": "touchpoint"})
    row = out.iloc[0]
    assert pd.isna(row["touchpoint_ratio"]) and "fewer than 10" in row["touchpoint_reason"]
    assert r.view.n_below_min == 1 and r.view.min_outreach == 10
    big = pd.DataFrame(
        {
            "author": ["x"] * 12,
            "kind": ["email"] * 10 + ["meeting"] * 2,
            "direction": ["outbound"] * 10 + [None] * 2,
        }
    )
    _, o2 = go("activities", big, {"type": "touchpoint"})
    assert o2.iloc[0]["touchpoint_ratio"] == pytest.approx(0.6)
    assert pd.isna(o2.iloc[0]["touchpoint_reason"])
