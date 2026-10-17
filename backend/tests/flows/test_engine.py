from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from app.domain.schemas import GateConfig
from app.flows.memory import MemoryLoader
from app.flows.ports import FlowLimits, SourceError
from app.flows.schemas import CrmSource
from tests.flows.helpers import deals_frame, ds, run

F = {"deals": pd.DataFrame({"a": [1, 2, 3]})}
FILT = {"type": "filter", "conditions": [{"column": "a", "op": "gt", "value": 1}]}
BAD = {"type": "filter", "conditions": [{"column": "zz", "op": "gt", "value": 1}]}


def test_error_skips_descendants_only():
    nodes = [("d", ds()), ("bad", BAD), ("after", FILT), ("ok", FILT)]
    edges = [("d", "out", "bad", "in"), ("bad", "out", "after", "in"), ("d", "out", "ok", "in")]
    r = run(F, nodes, edges)
    assert r["d"].status == "ok" and r["ok"].status == "ok"
    assert r["bad"].status == "error" and "zz" in r["bad"].error
    assert r["after"].status == "skipped"


def test_target_runs_only_ancestors():
    nodes = [("d", ds()), ("f", FILT), ("other", FILT)]
    edges = [("d", "out", "f", "in"), ("d", "out", "other", "in")]
    assert set(run(F, nodes, edges, target="f")) == {"d", "f"}
    assert set(run(F, nodes, edges)) == {"d", "f", "other"}
    assert run(F, nodes, edges, target="nope")["nope"].status == "error"


def test_missing_source_and_unconnected_input():
    r = run({}, [("d", ds()), ("f", FILT)], [("d", "out", "f", "in")])
    assert r["d"].status == "error" and r["f"].status == "skipped"
    r = run(F, [("f", FILT)], [])
    assert r["f"].status == "error" and "not connected" in r["f"].error


def test_deadline():
    r = run(
        F, [("d", ds()), ("f", FILT)], [("d", "out", "f", "in")], limits=FlowLimits(timeout_s=0)
    )
    assert r["d"].status == "error" and "time limit" in r["d"].error
    assert r["f"].status == "skipped"


def test_preview_is_json_safe_and_capped():
    df = pd.DataFrame(
        {
            "f": [1.5, np.nan, np.inf, -np.inf] * 50,
            "d": pd.to_datetime(["2025-01-01", None] * 100),
            "t": pd.to_datetime(["2025-01-01 10:30", "2025-01-02 00:00"] * 100),
            "i": np.arange(200),
            "b": [True, False] * 100,
            "s": ["x"] * 200,
        }
    )
    r = run({"deals": df}, [("d", ds())], [])["d"]
    json.dumps(r.preview, allow_nan=False)
    assert len(r.preview) == 100 and r.n_rows == 200
    p = r.preview[:4]
    assert [x["f"] for x in p] == [1.5, None, None, None]
    assert p[0]["d"] == "2025-01-01" and p[1]["d"] is None
    assert p[0]["t"].startswith("2025-01-01T10:30")
    assert {c.name: c.dtype for c in r.columns} == {
        "f": "number",
        "d": "date",
        "t": "datetime",
        "i": "integer",
        "b": "boolean",
        "s": "text",
    }


def test_dtype_mapping_object_columns():
    from datetime import date

    df = pd.DataFrame(
        {
            "o": [True, None, False],
            "dt": [date(2025, 1, 1), None, date(2025, 1, 2)],
            "mix": [1, "a", None],
        }
    )
    r = run({"deals": df}, [("d", ds())], [])["d"]
    assert {c.name: c.dtype for c in r.columns} == {"o": "boolean", "dt": "date", "mix": "other"}
    assert r.preview[0]["dt"] == "2025-01-01"


def test_memory_loader_cap_and_missing():
    ml = MemoryLoader({"deals": F["deals"]})
    out = ml.load(CrmSource(table="deals"), 2)
    assert len(out) == 2 and out.attrs["capped"]
    with pytest.raises(SourceError):
        ml.load(CrmSource(table="accounts"), 10)
    r = run(F, [("d", ds())], [], limits=FlowLimits(max_rows=2))["d"]
    assert r.n_rows == 2 and any("capped" in w for w in r.warnings)


def stats_cfg(**kw):
    return {
        "type": "stats",
        "group_by": "lead_source",
        "outcome": "is_won",
        "outcome_kind": "rate",
        **kw,
    }


def test_stats_planted_inbound_verified():
    from tests.flows.helpers import chain

    df = deals_frame("planted", 1, 1500)
    r = chain({"deals": df}, stats_cfg())
    rows = {x.group: x for x in r.view.rows}
    assert rows["inbound"].status == "verified" and rows["inbound"].diff > 0
    assert rows["inbound"].diff_ci_low > 0
    assert r.view.method.startswith("wilson")
    assert r.view.excluded_missing > 0  # open deals have no outcome


def test_stats_noise_verifies_nothing():
    from tests.flows.helpers import chain

    df = deals_frame("noise", 1, 1500)
    for gb in ("lead_source", "segment"):
        r = chain({"deals": df}, stats_cfg(group_by=gb))
        assert all(x.status == "not_verified" for x in r.view.rows)
        assert all(x.reasons for x in r.view.rows)


def test_stats_median_and_hand_values():
    from tests.flows.helpers import chain

    rng = np.random.default_rng(3)
    df = pd.DataFrame(
        {"g": ["a"] * 60 + ["b"] * 60, "v": np.r_[rng.normal(100, 5, 60), rng.normal(10, 1, 60)]}
    )
    r = chain(
        {"deals": df},
        {"type": "stats", "group_by": "g", "outcome": "v", "outcome_kind": "median"},
        gates=GateConfig(bootstrap_resamples=200),
    )
    a, b = r.view.rows
    assert a.status == "verified" and a.diff > 0 and b.diff < 0
    assert abs(a.value - df.v[:60].median()) < 1e-9
    # tiny groups: not verified with the n reason
    r = chain(
        {"deals": df.head(10)},
        {"type": "stats", "group_by": "g", "outcome": "v", "outcome_kind": "median"},
    )
    assert r.view.rows[0].status == "not_verified"
    assert any("n = " in x for x in r.view.rows[0].reasons)


def model_cfg(kind="logistic_regression", target="is_won", feats=("lead_source", "segment")):
    return {"type": "model", "kind": kind, "target": target, "features": list(feats)}


def model_run(df, cfg, seed=7):
    nodes = [("d", ds()), ("s", {"type": "split", "seed": seed}), ("m", cfg)]
    edges = [("d", "out", "s", "in"), ("s", "train", "m", "train"), ("s", "test", "m", "test")]
    return run({"deals": df}, nodes, edges, gates=GateConfig(bootstrap_resamples=200))["m"]


def test_logistic_planted_verified():
    df = deals_frame("planted", 1, 2000)
    df = df[df.is_won.notna()]
    r = model_run(df, model_cfg())
    assert r.status == "ok", r.error
    assert r.view.status == "verified", r.view.reasons
    acc = r.view.metrics[0]
    assert acc.ci_low > acc.baseline
    assert r.view.confusion is not None and "probability" in r.preview[0]
    assert any(c["feature"] == "lead_source=inbound" for c in r.view.coefficients)


def test_logistic_random_target_not_verified():
    rng = np.random.default_rng(5)
    df = pd.DataFrame(
        {"x": rng.normal(size=600), "c": rng.choice(list("abc"), 600), "y": rng.random(600) < 0.5}
    )
    r = model_run(df, model_cfg(target="y", feats=("x", "c")))
    assert r.view.status == "not_verified" and r.view.reasons


def test_logistic_small_test_reports_every_reason():
    df = pd.DataFrame({"x": np.arange(40.0), "y": [True, False] * 20})
    r = model_run(df, model_cfg(target="y", feats=("x",)))
    assert r.view.status == "not_verified"
    assert any("test set too small" in x for x in r.view.reasons)
    assert len(r.view.reasons) >= 3


def test_linear_regression():
    rng = np.random.default_rng(1)
    x = rng.normal(size=400)
    df = pd.DataFrame({"x": x, "y": 3 * x + rng.normal(size=400)})
    r = model_run(df, model_cfg("linear_regression", "y", ("x",)))
    assert r.view.status == "verified"
    r2 = r.view.metrics[0]
    assert r2.name == "r2" and r2.value > 0.8 and r2.ci_low > 0 and r2.baseline == 0
    noise = pd.DataFrame({"x": rng.normal(size=400), "y": rng.normal(size=400)})
    assert (
        model_run(noise, model_cfg("linear_regression", "y", ("x",))).view.status == "not_verified"
    )
    df.loc[:20, "x"] = np.nan
    assert model_run(df, model_cfg("linear_regression", "y", ("x",))).view.dropped_missing == 21
