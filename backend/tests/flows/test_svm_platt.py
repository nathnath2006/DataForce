"""SVM probabilities come from a Platt sigmoid on out-of-fold decision values (review #1)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.flows.blocks import model as model_block
from app.flows.scoring import PROBABILITY_CAVEAT
from tests.flows.helpers import ds


def _frame(n=1600, seed=3):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, 8))
    z = x[:, 0] * 1.2 + x[:, 1] * 0.8 - x[:, 2] * 0.6
    y = rng.random(n) < 1 / (1 + np.exp(-z))
    df = pd.DataFrame(x, columns=[f"x{i}" for i in range(8)])
    df["won"] = y
    return df


def _fit(df, c=100.0):
    nodes = [
        ("d", ds("deals")),
        ("s", {"type": "split", "test_fraction": 0.5, "seed": 1}),
        (
            "m",
            {
                "type": "model",
                "kind": "svm",
                "kernel": "rbf",
                "C": c,
                "target": "won",
                "features": [f"x{i}" for i in range(8)],
                "positive_value": True,
            },
        ),
    ]
    edges = [("d", "out", "s", "in"), ("s", "train", "m", "train"), ("s", "test", "m", "test")]
    cap: dict = {}
    from app.flows.engine import run_graph
    from app.flows.memory import MemoryLoader
    from app.flows.ports import FlowLimits
    from tests.flows.helpers import FAST, graph

    res = run_graph(
        graph(nodes, edges), MemoryLoader({"deals": df}), FAST, FlowLimits(), "m", capture=cap
    )
    return res["m"], cap["m"]


def _ece(p, y, bins=10):
    idx = np.minimum((p * bins).astype(int), bins - 1)
    return sum(
        (idx == b).mean() * abs(p[idx == b].mean() - y[idx == b].mean())
        for b in range(bins)
        if (idx == b).any()
    )


def test_out_of_fold_platt_is_better_calibrated_at_high_c(monkeypatch):
    df = _frame()
    res, out = _fit(df)
    ece_oof = _ece(out["probability"].to_numpy(), out["won"].to_numpy().astype(float))

    def in_sample(cfg, gamma, a, y, seed, warnings):
        from sklearn.svm import SVC

        return SVC(kernel=cfg.kernel, C=cfg.C, gamma=gamma).fit(a, y).decision_function(a)

    monkeypatch.setattr(model_block, "_oof_decision", in_sample)
    _, out2 = _fit(df)
    ece_in = _ece(out2["probability"].to_numpy(), out2["won"].to_numpy().astype(float))
    assert ece_oof < ece_in - 0.05
    assert PROBABILITY_CAVEAT in res.view.caveats
