"""Deal velocity, engagement score and rep touchpoint ratio (hand-computed expectations)."""

from __future__ import annotations

from datetime import date

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


def test_velocity_index_and_flags():
    # stays in "qual": d1 10, d2 20, d3 30 -> median 20. d3 is still in "proposal" for 10 days
    # (up to 2026-04-01), d1 and d2 stay 10 and 30 days in proposal -> median 20 (completed only).
    rows = []

    def ev(deal, stage, at):
        rows.append({"deal_id": deal, "to_stage": stage, "changed_at": pd.Timestamp(at)})

    (
        ev("d1", "qual", "2026-01-01"),
        ev("d1", "proposal", "2026-01-11"),
        ev("d1", "closed_won", "2026-01-21"),
    )
    (
        ev("d2", "qual", "2026-01-01"),
        ev("d2", "proposal", "2026-01-21"),
        ev("d2", "closed_won", "2026-02-20"),
    )
    ev("d3", "qual", "2026-01-01"), ev("d3", "proposal", "2026-01-31"), ev("d3", "x", "2026-03-22")
    df = pd.DataFrame(rows)
    r, out = go("stage_events", df, {"type": "velocity"})
    assert r.status == "ok", r.error
    by = out.set_index("deal_id")
    # completed: qual 10/20/30 (median 20); proposal 10/30/50 (d3: 01-31 -> 03-22 = 50), median 30
    assert by.loc["d1", "days_in_qual"] == 10 and by.loc["d1", "days_in_proposal"] == 10
    assert by.loc["d1", "benchmark_days"] == 50 and by.loc["d1", "total_days"] == 20
    assert by.loc["d1", "velocity_index"] == 2.5 and by.loc["d1", "velocity_flag"] == "fast_track"
    assert by.loc["d2", "velocity_index"] == 1.0 and by.loc["d2", "velocity_flag"] == "normal"
    # d3: qual 30 + proposal 50 = 80, plus open stage "x" (10 days, no benchmark: skipped)
    assert round(by.loc["d3", "velocity_index"], 4) == 0.625
    assert by.loc["d3", "velocity_flag"] == "stagnant"
    assert "median" in r.view.benchmark_note and "input" in r.view.benchmark_note
    assert r.view.counts == {"fast_track": 1, "normal": 1, "stagnant": 1, "no_index": 0}
    # thresholds are configurable
    r2, out2 = go(
        "stage_events", df, {"type": "velocity", "fast_track_at": 3.0, "stagnant_below": 0.5}
    )
    assert list(out2.sort_values("deal_id")["velocity_flag"]) == ["normal", "normal", "normal"]
    with pytest.raises(ValueError, match="stagnant_below"):
        go("stage_events", df, {"type": "velocity", "fast_track_at": 0.5, "stagnant_below": 0.7})


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
    r, out = go("activities", df, {"type": "touchpoint"})
    by = out.set_index("author")
    assert by.loc["x", "meetings"] == 2 and by.loc["x", "outreach"] == 2
    assert by.loc["x", "touchpoint_ratio"] == 3.0  # 2 x 3 / 2
    assert by.loc["y", "outreach"] == 0 and pd.isna(by.loc["y", "touchpoint_ratio"])
    assert any("no outreach" in w for w in r.warnings)
    assert r.view.n_no_outreach == 1
