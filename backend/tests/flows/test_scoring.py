"""Scoring with saved JSON parameters reproduces the model and cluster blocks' own predictions."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.flows.engine import run_graph
from app.flows.memory import MemoryLoader
from app.flows.ports import FlowLimits
from app.flows.scoring import ModelSnapshot, ScoringError, score_frame
from tests.flows.helpers import FAST, ds, graph

KINDS = {
    "linear_regression": "linear",
    "logistic_regression": "logistic",
    "svm": "svm",
    "svr": "svr",
}


def data(n: int = 400, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    a, b = rng.normal(size=n), rng.normal(5, 2, size=n)
    seg = rng.choice(["smb", "mid", "ent"], size=n)
    y = 2 * a - b + (seg == "ent") * 1.5 + rng.normal(0, 0.5, size=n)
    return pd.DataFrame(
        {"a": a, "b": b, "seg": seg, "y": y, "won": y > np.median(y), "flag": rng.random(n) > 0.5}
    )


def train(cfg: dict, df: pd.DataFrame):
    g = graph(
        [
            ("d", ds("deals")),
            ("s", {"type": "split", "test_fraction": 0.3, "seed": 3}),
            ("m", cfg),
        ],
        [("d", "out", "s", "in"), ("s", "train", "m", "train"), ("s", "test", "m", "test")],
    )
    cap: dict = {}
    res = run_graph(g, MemoryLoader({"deals": df}), FAST, FlowLimits(), "m", capture=cap)
    assert res["m"].status == "ok", res["m"].error
    return res["m"], cap["m"]


def snap(kind: str, res) -> ModelSnapshot:
    return ModelSnapshot("i", "m", kind, res.model_params, [], "verified")


@pytest.mark.parametrize(
    ("kind", "kernel"),
    [("linear_regression", "linear"), ("svr", "linear"), ("svr", "rbf")],
)
def test_regression_reproduces(kind, kernel):
    cfg = {"type": "model", "kind": kind, "target": "y", "features": ["a", "b", "seg", "flag"]}
    if kind == "svr":
        cfg["kernel"] = kernel
    res, out = train(cfg, data())
    sc = score_frame(snap(KINDS[kind], res), out)
    assert np.allclose(sc.columns["score"], out["prediction"], atol=1e-9, rtol=0)


@pytest.mark.parametrize(
    ("kind", "kernel"),
    [("logistic_regression", "linear"), ("svm", "linear"), ("svm", "rbf")],
)
def test_classifier_reproduces(kind, kernel):
    cfg = {
        "type": "model",
        "kind": kind,
        "target": "won",
        "features": ["a", "b", "seg"],
        "positive_value": True,
    }
    if kind == "svm":
        cfg["kernel"] = kernel
    res, out = train(cfg, data())
    sc = score_frame(snap(KINDS[kind], res), out)
    assert np.allclose(sc.columns["score"], out["probability"], atol=1e-9, rtol=0)
    assert (sc.columns["score_class"].to_numpy() == out["prediction"].to_numpy()).all()


def test_kmeans_reproduces():
    df = data()
    g = graph(
        [("d", ds("deals")), ("c", {"type": "cluster", "k": 3, "features": ["a", "b"]})],
        [("d", "out", "c", "in")],
    )
    cap: dict = {}
    res = run_graph(g, MemoryLoader({"deals": df}), FAST, FlowLimits(), "c", capture=cap)["c"]
    sc = score_frame(snap("kmeans", res), cap["c"])
    assert (sc.columns["score"].astype(int).to_numpy() == cap["c"]["cluster"].to_numpy()).all()


def test_unseen_category_missing_value_and_missing_column():
    res, out = train(
        {"type": "model", "kind": "linear_regression", "target": "y", "features": ["a", "seg"]},
        data(),
    )
    m = snap("linear", res)
    base = score_frame(m, out.head(3)).columns["score"].to_numpy()
    other = out.head(3).copy()
    other["seg"] = "never-seen"
    other2 = out.head(3).copy()
    other2["seg"] = "other"
    # an unseen value is scored like "other" (all zeros when training had no such column)
    assert np.allclose(
        score_frame(m, other).columns["score"], score_frame(m, other2).columns["score"]
    )
    assert not np.allclose(score_frame(m, other).columns["score"], base)
    miss = out.head(3).copy()
    miss["a"] = np.nan
    r = score_frame(m, miss)
    assert r.n_imputed == 3 and r.columns["score"].notna().all()
    with pytest.raises(ScoringError, match="'a'"):
        score_frame(m, out.drop(columns=["a"]))


def test_score_block_status_and_errors():
    res, out = train(
        {"type": "model", "kind": "linear_regression", "target": "y", "features": ["a", "b"]},
        data(),
    )
    m = ModelSnapshot(
        "11111111-1111-1111-1111-111111111111", "M", "linear", res.model_params, [], "not_verified"
    )
    g = graph(
        [("d", ds("deals")), ("s", {"type": "score", "model_id": m.id})], [("d", "out", "s", "in")]
    )
    frames = {"deals": out[["a", "b"]]}
    r = run_graph(
        g, MemoryLoader(frames), FAST, FlowLimits(), "s", models={m.id: m}, today=date(2026, 1, 1)
    )["s"]
    assert r.status == "ok" and r.view.status == "not_verified"
    assert "score" in [c.name for c in r.columns]
    gone = run_graph(g, MemoryLoader(frames), FAST, FlowLimits(), "s")["s"]
    assert gone.status == "error" and "does not exist" in gone.error
    bad = run_graph(
        g, MemoryLoader({"deals": out[["a"]]}), FAST, FlowLimits(), "s", models={m.id: m}
    )["s"]
    assert bad.status == "error" and "'b'" in bad.error


def test_parameters_that_do_not_fit_give_a_scoring_error():
    cfg = {"type": "model", "kind": "svr", "target": "y", "features": ["a", "b", "seg", "flag"]}
    res, out = train({**cfg, "kernel": "rbf"}, data())
    bad = dict(res.model_params)
    bad["support_vectors"] = [row[:-1] for row in bad["support_vectors"]]  # one feature short
    with pytest.raises(ScoringError, match="do not fit"):
        score_frame(ModelSnapshot("i", "m", "svr", bad, [], "verified"), out)
    lin, out2 = train({**cfg, "kind": "linear_regression"}, data())
    broken = {k: v for k, v in lin.model_params.items() if k != "intercept"}
    with pytest.raises(ScoringError, match="do not fit"):
        score_frame(ModelSnapshot("i", "m", "linear", broken, [], "verified"), out2)
