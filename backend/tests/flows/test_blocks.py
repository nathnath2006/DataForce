from __future__ import annotations

import numpy as np
import pandas as pd

from app.flows.ports import FlowLimits
from tests.flows.helpers import chain, ds, run

DF = pd.DataFrame(
    {
        "name": ["Alpha", "beta", "Gamma", None, "alphabet"],
        "n": [1, 2, 3, 4, None],
        "r": ["a", "a", "b", "b", "b"],
        "flag": [True, False, True, None, False],
        "d": pd.to_datetime(["2025-01-01", "2025-01-11", "2025-02-01", None, "2025-03-01"]),
    }
)
F = {"deals": DF}


def vals(res, col):
    return [r[col] for r in res.preview]


def flt(conds, mode="all"):
    return {"type": "filter", "mode": mode, "conditions": conds}


def test_filter_ops():
    def f(c, mode="all"):
        return chain(F, flt(c, mode))

    assert vals(f([{"column": "n", "op": "gt", "value": 2}]), "n") == [3, 4]
    assert vals(f([{"column": "n", "op": "ne", "value": 2}]), "n") == [1, 3, 4]  # null excluded
    assert f([{"column": "name", "op": "contains", "value": "ALPHA"}]).n_rows == 2
    assert f([{"column": "name", "op": "not_contains", "value": "alpha"}]).n_rows == 2
    assert f([{"column": "name", "op": "is_null"}]).n_rows == 1
    assert f([{"column": "n", "op": "not_null"}]).n_rows == 4
    assert f([{"column": "r", "op": "in", "value": ["a", "zz"]}]).n_rows == 2
    assert f([{"column": "r", "op": "in", "value": []}]).n_rows == 0
    assert f([{"column": "d", "op": "ge", "value": "2025-02-01"}]).n_rows == 2
    assert f([{"column": "flag", "op": "eq", "value": True}]).n_rows == 2
    any_ = f(
        [{"column": "r", "op": "eq", "value": "a"}, {"column": "n", "op": "eq", "value": 4}], "any"
    )
    assert any_.n_rows == 3
    assert f([]).n_rows == 5


def test_filter_type_mismatch_is_clean_error():
    r = chain(F, flt([{"column": "n", "op": "gt", "value": "abc"}]))
    assert r.status == "error" and "cannot compare" in r.error
    r = chain(F, flt([{"column": "n", "op": "contains", "value": "a"}]))
    assert r.status == "error"
    r = chain(F, flt([{"column": "nope", "op": "eq", "value": 1}]))
    assert r.status == "error" and "nope" in r.error


def test_sort_limit():
    r = chain(F, {"type": "sort", "keys": [{"column": "n", "descending": True}], "limit": 3})
    assert vals(r, "n") == [4, 3, 2]
    r = chain(F, {"type": "sort", "keys": [{"column": "n"}]})
    assert vals(r, "n")[-1] is None  # nulls last


def test_columns_keep_rename_computed():
    cfg = {
        "type": "columns",
        "keep": ["n", "d", "r"],
        "rename": {"n": "x"},
        "computed": [
            {"name": "x2", "op": "mul", "left": {"column": "x"}, "right": {"value": 2}},
            {"name": "inv", "op": "div", "left": {"value": 1}, "right": {"column": "x"}},
            {"name": "z", "op": "div", "left": {"column": "x"}, "right": {"value": 0}},
            {
                "name": "b",
                "op": "bucket",
                "left": {"column": "x"},
                "edges": [2, 3],
                "labels": ["lo", "mid", "hi"],
            },
        ],
    }
    r = chain(F, cfg)
    assert [c.name for c in r.columns][:3] == ["x", "d", "r"]
    assert vals(r, "x2") == [2, 4, 6, 8, None]
    assert vals(r, "inv")[:2] == [1.0, 0.5]
    assert set(vals(r, "z")) == {None}
    assert vals(r, "b") == ["lo", "mid", "hi", "hi", None]  # edge 2 goes to the upper bucket
    dd = {
        "type": "columns",
        "computed": [
            {
                "name": "days",
                "op": "days_between",
                "left": {"column": "d"},
                "right": {"column": "d"},
            }
        ],
    }
    assert vals(chain(F, dd), "days")[0] == 0
    frames = {
        "deals": pd.DataFrame(
            {"a": pd.to_datetime(["2025-01-01"]), "b": pd.to_datetime(["2025-01-11"])}
        )
    }
    dd["computed"][0]["left"] = {"column": "a"}
    dd["computed"][0]["right"] = {"column": "b"}
    assert vals(chain(frames, dd), "days") == [10.0]


def test_group_aggregates():
    cfg = {
        "type": "group",
        "by": ["r"],
        "aggregations": [
            {"fn": "count", "as": "rows"},
            {"column": "n", "fn": "count", "as": "nn"},
            {"column": "n", "fn": "sum", "as": "s"},
            {"column": "n", "fn": "mean", "as": "m"},
            {"column": "n", "fn": "median", "as": "med"},
            {"column": "n", "fn": "min", "as": "lo"},
            {"column": "n", "fn": "max", "as": "hi"},
            {"column": "name", "fn": "count_distinct", "as": "dn"},
        ],
    }
    r = chain(F, cfg)
    a, b = r.preview
    assert (a["r"], a["rows"], a["nn"], a["s"], a["m"]) == ("a", 2, 2, 3, 1.5)
    assert (b["r"], b["rows"], b["nn"], b["s"], b["med"], b["lo"], b["hi"], b["dn"]) == (
        "b",
        3,
        2,
        7,
        3.5,
        3,
        4,
        2,
    )
    bad = chain(
        F,
        {
            "type": "group",
            "by": ["r"],
            "aggregations": [{"column": "name", "fn": "sum", "as": "s"}],
        },
    )
    assert bad.status == "error"


def test_group_cap_warns():
    from app.domain.schemas import GateConfig
    from app.flows.blocks import group
    from app.flows.blocks._common import Ctx
    from app.flows.memory import MemoryLoader
    from app.flows.schemas import GroupConfig

    cfg = GroupConfig.model_validate({"by": ["k"], "aggregations": [{"fn": "count", "as": "c"}]})
    ctx = Ctx(GateConfig(), FlowLimits(max_rows=10), MemoryLoader({}))
    out = group.run(cfg, {"in": pd.DataFrame({"k": range(50)})}, ctx)
    assert len(out.frames["out"]) == 10 and any("capped" in w for w in out.warnings)


def join_run(how, left, right, limits=None):
    cfg = {"type": "join", "how": how, "on": [{"left": "k", "right": "k2"}]}
    return run(
        {"deals": left, "accounts": right},
        [("l", ds("deals")), ("r", ds("accounts")), ("j", cfg)],
        [("l", "out", "j", "left"), ("r", "out", "j", "right")],
        limits=limits,
    )["j"]


def test_join_counts_and_suffix():
    left = pd.DataFrame({"k": [1, 2, 3, None], "v": list("abcd")})
    right = pd.DataFrame({"k2": [1, 1, 2, None], "v": list("wxyz")})
    inner = join_run("inner", left, right)
    assert inner.n_rows == 3  # k=1 twice, k=2 once; nulls never match
    assert "v_right" in [c.name for c in inner.columns]
    lj = join_run("left", left, right)
    assert lj.n_rows == 5  # 3 matches + unmatched 3 and null
    assert join_run("inner", left, right.assign(k2="x")).status == "error"  # type clash


def test_join_cap():
    left = pd.DataFrame({"k": [1] * 10})
    right = pd.DataFrame({"k2": [1] * 10})
    r = join_run("inner", left, right, limits=FlowLimits(max_rows=30))
    assert r.n_rows == 30 and any("capped" in w for w in r.warnings)


def test_pivot_totals():
    df = pd.DataFrame(
        {
            "reg": ["n", "n", "s", "s", "s"],
            "src": ["a", "b", "a", "a", "b"],
            "amt": [1.0, 2.0, 3.0, 4.0, 5.0],
        }
    )
    r = chain({"deals": df}, {"type": "pivot", "rows": ["reg"], "columns": "src"})
    assert r.view.column_values == ["a", "b", "Total"]
    cells = {tuple(x["keys"]): x["cells"] for x in r.view.rows}
    assert cells[("n",)] == [1, 1, 2] and cells[("s",)] == [2, 1, 3]
    assert cells[("Total",)] == [3, 2, 5]
    assert [c.name for c in r.columns] == ["reg", "a", "b", "Total"]
    r = chain(
        {"deals": df},
        {
            "type": "pivot",
            "rows": ["reg"],
            "columns": "src",
            "values": "amt",
            "fn": "mean",
            "totals": False,
        },
    )
    cells = {tuple(x["keys"]): x["cells"] for x in r.view.rows}
    assert cells == {("n",): [1.0, 2.0], ("s",): [3.5, 5.0]}
    r = chain({"deals": df}, {"type": "pivot", "rows": ["reg"], "columns": "src", "max_columns": 1})
    assert r.view.truncated_columns == 1 and r.view.column_values[0] == "a"
    r = chain({"deals": df}, {"type": "pivot", "rows": ["reg"], "values": "amt", "fn": "sum"})
    assert [x["cells"] for x in r.view.rows] == [[3.0], [12.0], [15.0]]


def test_chart_points():
    df = pd.DataFrame({"x": ["a", "a", "b"], "y": [1.0, 3.0, 5.0], "s": ["p", "q", "p"]})
    r = chain({"deals": df}, {"type": "chart", "kind": "bar", "x": "x", "y": "y", "agg": "mean"})
    assert r.status == "ok" and r.preview == []
    assert r.view.series[0].points == [("a", 2.0), ("b", 5.0)]
    r = chain({"deals": df}, {"type": "chart", "kind": "bar", "x": "x"})
    assert r.view.series[0].points == [("a", 2.0), ("b", 1.0)]
    r = chain(
        {"deals": df},
        {
            "type": "chart",
            "kind": "scatter",
            "x": "y",
            "y": "y",
            "agg": "none",
            "series": "s",
            "max_points": 10,
        },
    )
    assert [s.name for s in r.view.series] == ["p", "q"]
    big = pd.DataFrame({"x": range(50), "y": 1.0})
    r = chain(
        {"deals": big},
        {"type": "chart", "kind": "scatter", "x": "x", "y": "y", "agg": "none", "max_points": 10},
    )
    assert r.view.truncated and len(r.view.series[0].points) == 10


def test_split_sizes_stratify_seed():
    df = pd.DataFrame({"a": range(100), "c": ["x"] * 50 + ["y"] * 50})
    nodes = [
        ("d", ds()),
        ("s", {"type": "split", "test_fraction": 0.2, "seed": 1, "stratify": "c"}),
    ]
    edges = [("d", "out", "s", "in")]
    r1 = run({"deals": df}, nodes, edges)["s"]
    r2 = run({"deals": df}, nodes, edges)["s"]
    assert r1.n_rows == 80 and r1.preview == r2.preview
    nodes.append(("m", {"type": "chart", "kind": "bar", "x": "c"}))
    r = run({"deals": df}, nodes, [*edges, ("s", "test", "m", "in")])["m"]
    assert sum(p[1] for p in r.view.series[0].points) == 20
    assert dict(r.view.series[0].points) == {"x": 10.0, "y": 10.0}


def test_kmeans_recovers_blobs():
    rng = np.random.default_rng(0)
    pts = np.vstack([rng.normal(c, 0.3, size=(50, 2)) for c in ((0, 0), (10, 10), (0, 10))])
    df = pd.DataFrame(pts, columns=["a", "b"])
    r = chain({"deals": df}, {"type": "cluster", "k": 3, "features": ["a", "b"]})
    assert r.view.status == "exploratory" and sorted(r.view.sizes) == [50, 50, 50]
    assert r.view.metrics[0].value > 0.8
    got = sorted((round(c["a"]), round(c["b"])) for c in r.view.centroids)
    assert got == [(0, 0), (0, 10), (10, 10)]
    labels = [p["cluster"] for p in r.preview]
    assert len(set(labels[:50])) == 1
