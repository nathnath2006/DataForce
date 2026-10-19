from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
from scipy.special import expit

from app.flows.blocks.dedup import jaro_winkler, levenshtein_ratio, normalise
from app.flows.blocks.domain import extract_domain, is_free
from app.flows.engine import run_graph
from app.flows.memory import MemoryLoader
from app.flows.ports import FlowLimits
from tests.flows.helpers import FAST, chain, ds, graph, run


def col(res, name):
    return [r[name] for r in res.preview]


# ---- dedup ----------------------------------------------------------------------------------
def test_normalise_and_similarity():
    assert normalise("Acme, Inc.") == "acme"
    assert normalise("ACME Corp") == "acme"
    assert normalise("Société Générale SAS") == "societe generale"
    assert normalise("Group") == "group"  # never reduced to nothing
    assert jaro_winkler("martha", "marhta") == pytest.approx(0.9611, abs=1e-4)
    assert levenshtein_ratio("kitten", "sitting") == pytest.approx(1 - 3 / 7)
    assert jaro_winkler("", "a") == 0.0


def test_dedup_acme_one_group_and_master():
    df = pd.DataFrame(
        {
            "name": ["Acme Corp", "Acme, Inc.", "ACME", "Globex", None, None],
            "city": ["Paris", "Paris", None, "Lyon", None, None],
        }
    )
    r = chain({"accounts": df}, {"type": "dedup", "column": "name"}, "accounts")
    assert r.status == "ok"
    assert col(r, "dedup_group") == [1, 1, 1, 2, 3, 4]
    # master: most complete row (2 cells), then longest text ("Acme, Inc.")
    assert col(r, "is_master") == [False, True, False, True, True, True]
    assert any("not merged" in w for w in r.warnings)


def test_dedup_threshold_methods_and_determinism():
    df = pd.DataFrame({"n": ["Dupont Consulting", "Dupond Consulting", "Zeta"]})
    lo = chain({"accounts": df}, {"type": "dedup", "column": "n", "threshold": 0.9}, "accounts")
    hi = chain({"accounts": df}, {"type": "dedup", "column": "n", "threshold": 1.0}, "accounts")
    assert col(lo, "dedup_group") == [1, 1, 2]
    assert col(hi, "dedup_group") == [1, 2, 3]
    lev = chain(
        {"accounts": df}, {"type": "dedup", "column": "n", "method": "levenshtein"}, "accounts"
    )
    assert col(lev, "dedup_group") == [1, 1, 2]
    again = chain({"accounts": df}, {"type": "dedup", "column": "n", "threshold": 0.9}, "accounts")
    assert col(again, "dedup_group") == col(lo, "dedup_group")


def test_dedup_blocking_and_edge_cases():
    df = pd.DataFrame({"n": ["abc corp", "xbc corp"]})  # differ in the first letter: not compared
    r = chain({"accounts": df}, {"type": "dedup", "column": "n", "threshold": 0.8}, "accounts")
    assert col(r, "dedup_group") == [1, 2]
    one = chain({"accounts": df.head(1)}, {"type": "dedup", "column": "n"}, "accounts")
    assert col(one, "is_master") == [True]
    empty = chain({"accounts": df.head(0)}, {"type": "dedup", "column": "n"}, "accounts")
    assert empty.status == "ok" and empty.n_rows == 0
    missing = chain({"accounts": df}, {"type": "dedup", "column": "zz"}, "accounts")
    assert missing.status == "error"


def test_dedup_cap_warning():
    df = pd.DataFrame({"n": [f"name{i % 7}" for i in range(50_001)]})
    r = chain(
        {"accounts": df},
        {"type": "dedup", "column": "n"},
        "accounts",
        limits=FlowLimits(max_rows=60_000),
    )
    assert r.status == "ok" and r.n_rows == 50_000
    assert any("capped at 50000" in w for w in r.warnings)


# ---- aging ----------------------------------------------------------------------------------
def run_today(frames, cfg, today):
    g = graph([("d", ds("deals")), ("b", cfg)], [("d", "out", "b", "in")])
    return run_graph(g, MemoryLoader(frames), FAST, FlowLimits(), "b", today=today)["b"]


def test_aging_exact_and_stagnant_condition():
    df = pd.DataFrame(
        {
            "created": pd.to_datetime(
                ["2026-01-01", "2026-02-20", None, "2026-03-31", "2026-04-02"]
            ),
            "stage": ["proposal", "proposal", "proposal", "closed_won", "proposal"],
        }
    )
    cfg = {
        "type": "aging",
        "column": "created",
        "stagnant_after_days": 30,
        "where": [{"column": "stage", "op": "ne", "value": "closed_won"}],
    }
    r = run_today({"deals": df}, cfg, date(2026, 4, 1))
    assert col(r, "days_since") == [90, 40, None, 1, -1]
    assert col(r, "stagnant") == [True, True, False, False, False]
    again = run_today({"deals": df}, cfg, date(2026, 4, 1))
    assert again.preview == r.preview
    assert any("no date" in w for w in r.warnings)


def test_aging_boundary_and_empty():
    df = pd.DataFrame({"c": pd.to_datetime(["2026-03-02", "2026-03-01"])})
    r = run_today({"deals": df}, {"type": "aging", "column": "c"}, date(2026, 4, 1))
    assert col(r, "days_since") == [30, 31]
    assert col(r, "stagnant") == [False, True]  # strictly greater than N
    e = run_today({"deals": df.head(0)}, {"type": "aging", "column": "c"}, date(2026, 4, 1))
    assert e.status == "ok" and e.n_rows == 0


# ---- forecast -------------------------------------------------------------------------------
def test_forecast_defaults_and_groups():
    df = pd.DataFrame(
        {
            "amount": [1000.0, 2000.0, None, 500.0, 100.0],
            "stage": ["Prospecting", "negotiation", "proposal", "closed_lost", "weird"],
            "owner": ["a", "a", "b", "b", "b"],
        }
    )
    cfg = {"type": "forecast", "amount": "amount", "stage": "stage"}
    r = chain({"deals": df}, cfg)
    assert col(r, "weighted_amount") == [100.0, 1200.0, None, 0.0, None]
    assert any("not a statistical estimate" in w for w in r.warnings)
    assert any("1 rows have a stage" in w for w in r.warnings)
    g = chain({"deals": df}, {**cfg, "group_by": "owner"})
    assert col(g, "owner") == ["a", "b"]
    assert col(g, "weighted_amount") == [1300.0, 0.0]
    assert col(g, "n") == [2, 3]
    custom = chain({"deals": df}, {**cfg, "probabilities": {"prospecting": 50}})
    assert col(custom, "weighted_amount")[0] == 500.0
    assert col(custom, "weighted_amount")[1] is None


def test_forecast_invalid_probability_rejected_by_schema():
    with pytest.raises(ValueError):
        graph(
            [("b", {"type": "forecast", "amount": "a", "stage": "s", "probabilities": {"x": 120}})],
            [],
        )


# ---- window ---------------------------------------------------------------------------------
W = pd.DataFrame(
    {
        "rep": ["a", "a", "a", "b", "b"],
        "t": [3, 1, 2, 1, 2],
        "v": [30.0, 10.0, None, 5.0, 0.0],
    }
)


def win(**kw):
    return chain({"deals": W}, {"type": "window", "order_by": "t", "alias": "w", **kw})


def test_window_lag_lead_pct():
    p = ["rep"]
    assert col(win(fn="lag", column="v", partition_by=p), "w") == [None, None, 10.0, None, 5.0]
    assert col(win(fn="lead", column="v", partition_by=p), "w") == [None, None, 30.0, 0.0, None]
    assert col(win(fn="pct_change", column="v", partition_by=p), "w") == [
        None,
        None,
        None,
        None,
        -1.0,
    ]
    assert col(win(fn="lag", column="v", k=2, partition_by=p), "w")[0] == 10.0


def test_window_pct_change_zero_base_is_null():
    df = pd.DataFrame({"t": [1, 2, 3], "v": [0.0, 5.0, 10.0]})
    r = chain({"deals": df}, {"type": "window", "fn": "pct_change", "column": "v", "order_by": "t"})
    assert col(r, "window_value") == [None, None, 1.0]


def test_window_rolling():
    p = ["rep"]
    assert col(win(fn="rolling_sum", column="v", k=2, partition_by=p), "w") == [
        30.0,
        10.0,
        10.0,
        5.0,
        5.0,
    ]
    assert col(win(fn="rolling_mean", column="v", k=2, partition_by=p), "w") == [
        30.0,
        10.0,
        10.0,
        5.0,
        2.5,
    ]
    assert col(win(fn="rolling_count", column="v", k=2, partition_by=p), "w") == [
        1.0,
        1.0,
        1.0,
        1.0,
        2.0,
    ]


def test_window_rank_row_number_ties():
    assert col(win(fn="rank"), "w") == [5.0, 1.0, 3.0, 1.0, 3.0]  # ties share the lowest rank
    assert col(win(fn="rank", partition_by=["rep"], descending=True), "w") == [
        1.0,
        3.0,
        2.0,
        2.0,
        1.0,
    ]
    assert col(win(fn="row_number"), "w") == [5.0, 1.0, 3.0, 2.0, 4.0]  # stable on ties


def test_window_validation_and_edges():
    assert win(fn="lag").status == "error"  # needs a value column
    assert win(fn="lag", column="v", alias="v").status == "error"
    one = chain(
        {"deals": W.head(1)}, {"type": "window", "fn": "lag", "column": "v", "order_by": "t"}
    )
    assert col(one, "window_value") == [None]
    e = chain({"deals": W.head(0)}, {"type": "window", "fn": "row_number", "order_by": "t"})
    assert e.status == "ok" and e.n_rows == 0
    nulls = pd.DataFrame({"t": [None, 1.0], "v": [1.0, 2.0]})
    r = chain({"deals": nulls}, {"type": "window", "fn": "lag", "column": "v", "order_by": "t"})
    assert col(r, "window_value") == [2.0, None]  # null order sorts last


def test_window_qoq_per_owner():
    df = pd.DataFrame(
        {
            "owner": ["a", "a", "a", "b", "a"],
            "closed_on": pd.to_datetime(
                ["2025-01-15", "2025-02-10", "2025-04-01", "2025-05-05", None]
            ),
            "amount": [100.0, 100.0, 300.0, 50.0, 9.0],
        }
    )
    r = chain(
        {"deals": df},
        {
            "type": "window",
            "fn": "pct_change",
            "column": "amount",
            "order_by": "closed_on",
            "partition_by": ["owner"],
            "period": "quarter",
            "alias": "qoq",
        },
    )
    assert col(r, "owner") == ["a", "a", "b"]
    assert col(r, "period") == ["2025-Q1", "2025-Q2", "2025-Q2"]
    assert col(r, "amount") == [200.0, 300.0, 50.0]
    assert col(r, "qoq") == [None, 0.5, None]
    assert any("without a date" in w for w in r.warnings)


# ---- domain ---------------------------------------------------------------------------------
def test_domain_parser():
    assert extract_domain("Jane <jane@Gmail.com>") == "gmail.com"
    assert extract_domain("jane@sub.Acme.fr") == "sub.acme.fr"
    assert extract_domain("https://www.Acme.com:8080/path?q=1") == "acme.com"
    assert extract_domain("acme.com/x") == "acme.com"
    assert extract_domain("not a domain") is None
    assert extract_domain("") is None and extract_domain(None) is None
    assert is_free("gmail.com") and is_free("hotmail.fr") and is_free("yahoo.co.uk")
    assert is_free("gmx.de") and is_free("protonmail.com") and is_free("free.fr")
    assert not is_free("acme.com") and not is_free("gmail.com.evil.io")


def test_domain_block():
    df = pd.DataFrame({"e": ["a@gmail.com", "b@acme.com", None, "garbage"]})
    r = chain({"contacts": df}, {"type": "domain", "column": "e"}, "contacts")
    assert col(r, "domain") == ["gmail.com", "acme.com", None, None]
    assert col(r, "is_free_webmail") == [True, False, None, None]
    assert any("1 values" in w for w in r.warnings)


# ---- chronological split --------------------------------------------------------------------
def split_run(df, **kw):
    cfg = {"type": "split", "mode": "chronological", "date_column": "d", **kw}
    res = run(
        {"deals": df},
        [("d", ds()), ("s", cfg)],
        [("d", "out", "s", "in")],
        target="s",
    )
    return res["s"]


def test_chronological_split_order():
    d = pd.date_range("2025-01-01", periods=20, freq="D")
    df = pd.DataFrame({"d": d[::-1], "i": range(20)})  # shuffled order: newest first
    frames = {}
    g = graph(
        [("d", ds()), ("s", {"type": "split", "mode": "chronological", "date_column": "d"})],
        [("d", "out", "s", "in")],
    )
    run_graph(g, MemoryLoader({"deals": df}), FAST, FlowLimits(), "s", capture=frames)
    r = split_run(df, test_fraction=0.25)
    assert r.status == "ok" and r.n_rows == 15  # first output port: train
    ts = pd.DataFrame({"d": pd.date_range("2025-01-01", periods=20, freq="D")})
    tr, te = ts.iloc[:15], ts.iloc[15:]
    assert tr["d"].max() < te["d"].min()


def test_chronological_split_content_and_ties():
    df = pd.DataFrame(
        {
            "d": pd.to_datetime(["2025-01-05", "2025-01-01", "2025-01-03", "2025-01-03", None]),
            "i": [0, 1, 2, 3, 4],
        }
    )
    out = {}
    g = graph(
        [
            ("d", ds()),
            (
                "s",
                {
                    "type": "split",
                    "mode": "chronological",
                    "date_column": "d",
                    "test_fraction": 0.5,
                },
            ),
            ("tr", {"type": "sort", "keys": [{"column": "i"}]}),
            ("te", {"type": "sort", "keys": [{"column": "i"}]}),
        ],
        [("d", "out", "s", "in"), ("s", "train", "tr", "in"), ("s", "test", "te", "in")],
    )
    res = run_graph(g, MemoryLoader({"deals": df}), FAST, FlowLimits())
    # 4 dated rows, half in test: boundary date 2025-01-03 shared -> both 01-03 rows go to test
    assert [r["i"] for r in res["tr"].preview] == [1]
    assert [r["i"] for r in res["te"].preview] == [0, 2, 3]
    assert any("without a date" in w for w in res["s"].warnings)
    del out


def test_chronological_split_errors_and_schema():
    same = pd.DataFrame({"d": pd.to_datetime(["2025-01-01"] * 4)})
    assert split_run(same).status == "error"
    assert split_run(pd.DataFrame({"d": pd.to_datetime(["2025-01-01"])})).status == "error"
    with pytest.raises(ValueError):
        graph([("s", {"type": "split", "mode": "chronological"})], [])


def test_chronological_split_feeds_a_verified_model():
    rng = np.random.default_rng(3)
    n = 400
    x = rng.normal(size=n)
    df = pd.DataFrame(
        {
            "d": pd.date_range("2024-01-01", periods=n, freq="D"),
            "x": x,
            "y": 2 * x + rng.normal(scale=0.1, size=n),
        }
    )
    res = run(
        {"deals": df},
        [
            ("d", ds()),
            ("s", {"type": "split", "mode": "chronological", "date_column": "d"}),
            ("m", {"type": "model", "kind": "linear_regression", "target": "y", "features": ["x"]}),
        ],
        [("d", "out", "s", "in"), ("s", "train", "m", "train"), ("s", "test", "m", "test")],
        target="m",
    )["m"]
    assert res.view.status == "verified"
    assert res.view.n_test == 100


# ---- SVM / SVR ------------------------------------------------------------------------------
def model_run(df, cfg, split=None):
    res = run(
        {"deals": df},
        [("d", ds()), ("s", split or {"type": "split", "seed": 1}), ("m", cfg)],
        [("d", "out", "s", "in"), ("s", "train", "m", "train"), ("s", "test", "m", "test")],
        target="m",
    )
    return res["m"]


def clf_frame(separable: bool, n=600, seed=0):
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 2, n).astype(bool)
    x1 = rng.normal(size=n) + (3.0 * y if separable else 0.0)
    return pd.DataFrame({"y": y, "x1": x1, "x2": rng.normal(size=n)})


SVM = {"type": "model", "kind": "svm", "target": "y", "features": ["x1", "x2"]}


def test_svm_separable_verified_rbf_and_linear():
    for kernel in ("rbf", "linear"):
        r = model_run(clf_frame(True), {**SVM, "kernel": kernel})
        assert r.status == "ok", r.error
        assert r.view.status == "verified", r.view.reasons
        names = {m.name: m for m in r.view.metrics}
        assert names["auc"].value > 0.9 and names["auc"].ci_low > 0.5
        assert names["accuracy"].baseline < names["accuracy"].ci_low
        assert "probability" in r.preview[0] and 0 <= r.preview[0]["probability"] <= 1
        assert r.model_params["kernel"] == kernel
        assert (len(r.view.coefficients) > 0) == (kernel == "linear")


def test_svm_noise_not_verified():
    r = model_run(clf_frame(False), SVM)
    assert r.status == "ok"
    assert r.view.status == "not_verified"
    assert r.view.reasons


def test_svm_leak_not_verified():
    df = clf_frame(True)
    res = run(
        {"deals": df},
        [("d", ds()), ("m", SVM)],
        [("d", "out", "m", "train"), ("d", "out", "m", "test")],
        target="m",
    )["m"]
    assert res.view.status == "not_verified"


def test_svm_params_reproduce_predictions():
    df = clf_frame(True, n=300)
    df["seg"] = np.where(np.arange(len(df)) % 3 == 0, "a", "b")
    cfg = {**SVM, "features": ["x1", "x2", "seg"], "gamma": 0.2}
    r = model_run(df, cfg)
    p = r.model_params
    assert p["gamma"] == 0.2
    assert [f["name"] for f in p["features"]["numeric"]] == ["x1", "x2"]
    assert p["features"]["categorical"][0]["name"] == "seg"
    assert p["encoded_features"][:2] == ["x1", "x2"]
    # rebuild a test row's score from plain parameters
    row = r.preview[0]
    num = [(row[f["name"]] - f["mean"]) / f["std"] for f in p["features"]["numeric"]]
    cats = p["features"]["categorical"][0]["categories"]
    x = np.array(num + [1.0 if row["seg"] == c else 0.0 for c in cats])
    sv, dc = np.array(p["support_vectors"]), np.array(p["dual_coef"])
    f = (dc * np.exp(-p["gamma"] * ((sv - x) ** 2).sum(axis=1))).sum() + p["intercept"]
    assert expit(p["platt_a"] * f + p["platt_b"]) == pytest.approx(row["probability"], abs=1e-9)
    assert (f > 0) == row["prediction"]


def test_svm_support_vector_export_cap(monkeypatch):
    from app.flows.blocks import model as model_block

    monkeypatch.setattr(model_block, "MAX_EXPORTED_SV", 5)
    rbf = model_run(clf_frame(False), SVM)
    assert rbf.status == "ok"
    assert "support_vectors" not in rbf.model_params and rbf.model_params["exportable"] is False
    assert rbf.model_params["n_support_vectors"] > 5
    assert any("cannot be saved for scoring" in w for w in rbf.warnings)
    lin = model_run(clf_frame(False), {**SVM, "kernel": "linear"})
    assert lin.model_params["exportable"] is True and len(lin.model_params["coef"]) == 2


def test_svm_row_cap_warning():
    df = clf_frame(True, n=24_000)
    r = model_run(df, SVM, split={"type": "split", "seed": 1, "test_fraction": 0.1})
    assert r.status == "ok", r.error
    assert any("capped at 20000" in w for w in r.warnings)
    assert r.view.n_train == 20_000


def test_svr_verified_and_not():
    rng = np.random.default_rng(5)
    n = 500
    x = rng.normal(size=n)
    good = pd.DataFrame({"y": 3 * x + 10, "x": x})
    cfg = {"type": "model", "kind": "svr", "target": "y", "features": ["x"], "kernel": "linear"}
    r = model_run(good, cfg)
    assert r.view.status == "verified", r.view.reasons
    assert {m.name for m in r.view.metrics} == {"r2", "mae", "rmse"}
    assert r.model_params["y_std"] > 0
    bad = pd.DataFrame({"y": rng.normal(size=n), "x": x})
    rb = model_run(bad, {**cfg, "kernel": "rbf"})
    assert rb.view.status == "not_verified"


def test_model_params_linear_logistic_kmeans():
    df = clf_frame(True)
    df["z"] = df["x1"] * 2 + 1
    lin = model_run(
        df, {"type": "model", "kind": "linear_regression", "target": "z", "features": ["x1"]}
    )
    assert lin.model_params["coef"] and "intercept" in lin.model_params
    log = model_run(
        df, {"type": "model", "kind": "logistic_regression", "target": "y", "features": ["x1"]}
    )
    assert len(log.model_params["coef"]) == 1 and log.model_params["positive_value"] is True
    km = chain({"deals": df}, {"type": "cluster", "k": 2, "features": ["x1", "x2"]})
    mp = km.model_params
    assert mp["features"] == ["x1", "x2"] and len(mp["centroids_scaled"]) == 2
    assert len(mp["scaler_mean"]) == 2 and len(mp["scaler_std"]) == 2


def test_dedup_big_block_warns_and_long_keys_are_truncated():
    from app.flows.blocks import dedup

    names = [f"a{i:04d}" for i in range(dedup.MAX_BLOCK + 5)]
    r = chain(
        {"accounts": pd.DataFrame({"n": names})},
        {"type": "dedup", "column": "n", "block_prefix": 1},
        "accounts",
    )
    assert any(f"over {dedup.MAX_BLOCK}" in w for w in r.warnings)
    long_a, long_b = "x" * 150 + "a", "x" * 150 + "b"  # equal once cut to MAX_KEY
    r = chain(
        {"accounts": pd.DataFrame({"n": [long_a, long_b]})},
        {"type": "dedup", "column": "n"},
        "accounts",
    )
    assert col(r, "dedup_group") == [1, 1]
