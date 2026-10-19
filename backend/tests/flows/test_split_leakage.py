"""Split warnings and post-outcome features (methods review #2)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tests.flows.helpers import ds, run


def _deals(n=600, seed=0):
    rng = np.random.default_rng(seed)
    won = rng.random(n) < 0.4
    return pd.DataFrame(
        {
            "deal_id": [f"d{i}" for i in range(n)],
            "is_won": won,
            "amount_eur": rng.normal(1000, 200, n),
            "cycle_days": np.where(won, rng.normal(30, 5, n), rng.normal(90, 5, n)),
            "closed_on": pd.Timestamp("2025-01-01") + pd.to_timedelta(rng.integers(0, 300, n), "D"),
        }
    )


def _split_res(df, cfg):
    r = run({"deals": df}, [("d", ds("deals")), ("s", cfg)], [("d", "out", "s", "in")])
    return r["s"]


def test_random_split_of_dated_data_warns():
    r = _split_res(_deals(), {"type": "split"})
    assert any("time order is ignored" in w and "chronological" in w for w in r.warnings)
    r2 = _split_res(_deals().drop(columns=["closed_on"]), {"type": "split"})
    assert not any("time order" in w for w in r2.warnings)


def test_chronological_boundary_ties_warn_with_both_numbers():
    df = _deals(200)
    df["closed_on"] = pd.Timestamp("2025-01-01")
    df.loc[:79, "closed_on"] = pd.Timestamp("2025-02-28")  # 40% close on the last day
    df.loc[80:, "closed_on"] = pd.Timestamp("2025-02-27") - pd.to_timedelta(
        np.arange(120) % 20, "D"
    )
    cfg = {"type": "split", "mode": "chronological", "date_column": "closed_on"}
    r = _split_res(df, cfg)
    assert any("40%" in w and "25%" in w for w in r.warnings)
    ok = _deals(200)
    ok["closed_on"] = pd.Timestamp("2025-01-01") + pd.to_timedelta(np.arange(200), "D")
    assert not any("test share" in w for w in _split_res(ok, cfg).warnings)


def _model(df, features):
    nodes = [
        ("d", ds("deals")),
        ("s", {"type": "split", "mode": "chronological", "date_column": "closed_on"}),
        (
            "m",
            {
                "type": "model",
                "kind": "logistic_regression",
                "target": "is_won",
                "features": features,
                "positive_value": True,
            },
        ),
    ]
    edges = [("d", "out", "s", "in"), ("s", "train", "m", "train"), ("s", "test", "m", "test")]
    return run({"deals": df}, nodes, edges)["m"]


def test_post_outcome_feature_makes_model_not_verified():
    r = _model(_deals(), ["amount_eur", "cycle_days"])
    assert r.status == "ok", r.error
    assert r.view.status == "not_verified"
    assert any("'cycle_days'" in x and "after the deal closes" in x for x in r.view.reasons)
    clean = _model(_deals(), ["amount_eur"])
    assert not any("after the deal closes" in x for x in clean.view.reasons)
