"""SR9 regressions: deadlines, bootstrap budget, leakage, row multiplication, pivot caps."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from app.domain.schemas import GateConfig
from app.flows.ports import FlowLimits
from tests.flows.helpers import chain, ds, run


def _median_df(n: int, groups: int) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    return pd.DataFrame({"g": rng.integers(0, groups, n).astype(str), "v": rng.random(n) * 100})


def _stats(by="g", out="v"):
    return {"type": "stats", "group_by": by, "outcome": out, "outcome_kind": "median"}


def test_stats_sr9_input_is_bounded():
    t = time.monotonic()
    r = chain({"deals": _median_df(20_000, 50)}, _stats(), gates=GateConfig())
    assert time.monotonic() - t < 10
    assert r.status == "ok" or "time limit" in (r.error or "") or "too many rows" in r.error
    if r.status == "ok":
        assert any("resamples lowered" in w for w in r.warnings)


def test_stats_group_cap():
    r = chain({"deals": _median_df(2000, 60)}, _stats())
    assert r.status == "error" and "too many groups" in r.error


def test_stats_deadline_clean_error():
    r = chain(
        {"deals": _median_df(20_000, 40)},
        _stats(),
        gates=GateConfig(),
        limits=FlowLimits(timeout_s=0.3),
    )
    assert r.status == "error" and "time limit" in r.error


def test_stats_too_many_rows():
    r = chain({"deals": _median_df(200_000, 50)}, _stats(), limits=FlowLimits(max_rows=300_000))
    assert r.status == "error" and "filter or sample first" in r.error


def _model_graph(same_split: bool, via_filter: bool = False):
    df = pd.DataFrame({"x": np.arange(200.0), "y": np.arange(200.0) * 2 + 1})
    nodes = [
        ("d", ds()),
        ("s", {"type": "split", "seed": 1}),
        ("s2", {"type": "split", "seed": 2}),
        ("f", {"type": "sort", "keys": [{"column": "x"}]}),
        ("m", {"type": "model", "kind": "linear_regression", "target": "y", "features": ["x"]}),
    ]
    edges = [("d", "out", "s", "in"), ("d", "out", "s2", "in"), ("s", "train", "m", "train")]
    if via_filter:
        edges += [("s", "test", "f", "in"), ("f", "out", "m", "test")]
    elif same_split:
        edges.append(("s", "test", "m", "test"))
    else:
        edges.append(("s2", "test", "m", "test"))
    return run({"deals": df}, nodes, edges)["m"]


def test_model_verified_only_with_same_split():
    assert _model_graph(True).view.status == "verified"
    r = _model_graph(False)
    assert r.view.status == "not_verified" and any("overlap" in x for x in r.view.reasons)


def test_model_same_split_through_row_preserving_block():
    r = _model_graph(True, via_filter=True)
    assert r.status == "ok", r.error
    assert not any("overlap" in x for x in r.view.reasons)


def test_model_same_dataset_both_ports_not_verified():
    df = pd.DataFrame({"x": np.arange(100.0), "y": np.arange(100.0)})
    nodes = [
        ("d", ds()),
        ("m", {"type": "model", "kind": "linear_regression", "target": "y", "features": ["x"]}),
    ]
    r = run({"deals": df}, nodes, [("d", "out", "m", "train"), ("d", "out", "m", "test")])["m"]
    assert r.view.status == "not_verified"


def test_join_multiplication_flag_propagates_to_stats():
    left = pd.DataFrame({"k": [1] * 40 + [2] * 40, "g": ["a"] * 40 + ["b"] * 40, "v": [1.0] * 80})
    right = pd.DataFrame({"k": [1, 1, 2, 2], "w": [1, 2, 3, 4]})
    nodes = [
        ("l", ds("deals")),
        ("r", ds("accounts")),
        ("j", {"type": "join", "how": "inner", "on": [{"left": "k", "right": "k"}]}),
        ("s", {"type": "sort", "keys": [{"column": "k"}]}),
        ("st", _stats()),
    ]
    edges = [
        ("l", "out", "j", "left"),
        ("r", "out", "j", "right"),
        ("j", "out", "s", "in"),
        ("s", "out", "st", "in"),
    ]
    res = run({"deals": left, "accounts": right}, nodes, edges)
    assert any("multiplied" in w for w in res["j"].warnings)
    st = res["st"]
    assert st.status == "ok"
    assert all(x.status == "not_verified" for x in st.view.rows)
    assert all("inflated" in x.reasons[-1] for x in st.view.rows)


def test_pivot_view_is_capped():
    df = pd.DataFrame({"r": np.arange(5000), "c": ["a", "b"] * 2500})
    r = chain({"deals": df}, {"type": "pivot", "rows": ["r"], "columns": "c", "totals": False})
    assert len(r.view.rows) <= 1000 and r.n_rows == 5000
    assert any("pivot view shows" in w for w in r.warnings)


def test_model_one_hot_width_cap():
    rng = np.random.default_rng(0)
    cols = {f"c{i}": rng.integers(0, 20, 400).astype(str) for i in range(30)}
    df = pd.DataFrame({**cols, "y": rng.random(400)})
    nodes = [
        ("d", ds()),
        ("s", {"type": "split", "seed": 1}),
        (
            "m",
            {"type": "model", "kind": "linear_regression", "target": "y", "features": list(cols)},
        ),
    ]
    edges = [("d", "out", "s", "in"), ("s", "train", "m", "train"), ("s", "test", "m", "test")]
    r = run({"deals": df}, nodes, edges)["m"]
    assert r.status == "error" and "encoded features" in r.error
