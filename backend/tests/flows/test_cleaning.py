"""standardize and regex blocks: every operation, safety rejections, long cells, nulls."""

from __future__ import annotations

import pandas as pd
import pytest
from pydantic import ValidationError

from app.flows.blocks._common import BlockError
from app.flows.blocks.regex import check_pattern
from app.flows.blocks.standardize import to_e164
from app.flows.engine import run_graph
from app.flows.memory import MemoryLoader
from app.flows.ports import FlowLimits
from tests.flows.helpers import FAST, ds, graph


def go(df: pd.DataFrame, cfg: dict):
    g = graph([("d", ds("contacts")), ("b", cfg)], [("d", "out", "b", "in")])
    cap: dict = {}
    r = run_graph(g, MemoryLoader({"contacts": df}), FAST, FlowLimits(), "b", capture=cap)["b"]
    return r, cap.get("b")


def sc(**kw):
    return {"type": "standardize", "columns": ["t"], "operations": ["trim"], **kw}


def std(values, ops, **kw):
    df = pd.DataFrame({"t": values})
    r, out = go(df, {"type": "standardize", "columns": ["t"], "operations": ops, **kw})
    assert r.status == "ok", r.error
    return r, out


@pytest.mark.parametrize(
    ("ops", "src", "want"),
    [
        (["trim"], "  a b  ", "a b"),
        (["collapse_spaces"], "a   b \t c", "a b c"),
        (["lower"], "AbC", "abc"),
        (["upper"], "AbC", "ABC"),
        (["title"], "jEAN-luc o'neil", "Jean-Luc O'neil"),
        (["remove_accents"], "Éléphant çà", "Elephant ca"),
        (["normalize_unicode"], "é", "é"),
        (["strip_punctuation"], "a.b, c-d!", "ab cd"),
        (["empty_to_null"], "   ", None),
        (["email"], "  Jo@Ex.COM ", "jo@ex.com"),
        (["trim", "lower", "remove_accents"], "  ÉCOLE ", "ecole"),
    ],
)
def test_operations(ops, src, want):
    _, out = std([src], ops)
    assert out["t"].iloc[0] == want


def test_nulls_stay_null_and_stats():
    r, out = std(["  x ", None, "", "y"], ["trim", "empty_to_null"])
    assert out["t"].tolist() == ["x", None, None, "y"]
    s = r.view.columns[0]
    assert (s.n_changed, s.n_null) == (2, 1)  # "  x " trimmed, "" became null; None unchanged


def test_map_values_case_options():
    _, out = std(["Paris", "paris", "x"], ["map_values"], mapping={"Paris": "FR-75"})
    assert out["t"].tolist() == ["FR-75", "paris", "x"]
    _, out = std(
        ["Paris", "paris", "x"],
        ["map_values"],
        mapping={"Paris": "FR-75"},
        mapping_ignore_case=True,
    )
    assert out["t"].tolist() == ["FR-75", "FR-75", "x"]


def test_map_limits():
    big = {str(i): "v" for i in range(201)}
    with pytest.raises(ValidationError):
        graph(
            [
                (
                    "b",
                    {
                        "type": "standardize",
                        "columns": ["t"],
                        "operations": ["map_values"],
                        "mapping": big,
                    },
                )
            ],
            [],
        )
    with pytest.raises(ValidationError):
        graph([("b", sc(operations=["map_values"]))], [])


@pytest.mark.parametrize(
    ("src", "want"),
    [
        ("06 12 34 56 78", "+33612345678"),
        ("06.12.34.56.78", "+33612345678"),
        ("+33 (0)6 12 34 56 78", "+33612345678"),
        ("0033 6 12 34 56 78", "+33612345678"),
        ("33612345678", "+33612345678"),
        ("+44 20 7946 0958", "+442079460958"),
        ("12345", None),
        ("abc", None),
        ("06 12 34", None),
    ],
)
def test_phone(src, want):
    assert to_e164(src, "FR") == want


def test_phone_flag_and_leave_as_is():
    r, out = std(["06 12 34 56 78", "call me"], ["phone_e164"])
    assert out["t"].tolist() == ["+33612345678", "call me"]
    assert r.view.columns[0].n_flagged == 1
    assert any("phone" in w for w in r.warnings)
    assert to_e164("2025550143", "US") == "+12025550143"


def test_new_column_and_conflict():
    df = pd.DataFrame({"t": [" A "]})
    r, out = go(
        df,
        {"type": "standardize", "columns": ["t"], "operations": ["trim"], "output": "new_column"},
    )
    assert out["t"].iloc[0] == " A " and out["t_std"].iloc[0] == "A"
    df["t_std"] = 1
    r, _ = go(
        df,
        {"type": "standardize", "columns": ["t"], "operations": ["trim"], "output": "new_column"},
    )
    assert r.status == "error" and "t_std" in r.error


def test_missing_column():
    r, _ = go(
        pd.DataFrame({"a": ["x"]}),
        {"type": "standardize", "columns": ["zz"], "operations": ["trim"]},
    )
    assert r.status == "error"


# ---- regex ----
def rx(values, **kw):
    df = pd.DataFrame({"t": values})
    r, out = go(df, {"type": "regex", "column": "t", **kw})
    return r, out


def test_extract():
    r, out = rx(["a@x.fr", "nope", None], mode="extract", pattern=r"(?P<user>\w+)@(?P<dom>[\w.]+)")
    assert out["dom"].tolist() == ["x.fr", None, None]
    assert out["user"].iloc[0] == "a"
    assert r.view.n_cells == 2 and r.view.n_matched == 1 and r.view.match_rate == 0.5


def test_extract_needs_named_group():
    r, _ = rx(["a"], mode="extract", pattern=r"(a)")
    assert r.status == "error" and "named group" in r.error


def test_replace_backrefs_and_ignore_case():
    r, out = rx(["John SMITH", None], mode="replace", pattern=r"(\w+) (\w+)", replacement=r"\2, \1")
    assert out["t"].tolist() == ["SMITH, John", None]
    r, out = rx(["ABC"], mode="replace", pattern="b", replacement="-", ignore_case=True, alias="o")
    assert out["o"].iloc[0] == "A-C" and out["t"].iloc[0] == "ABC"
    r, _ = rx(["a"], mode="replace", pattern="a", replacement=r"\5")
    assert r.status == "error"


def test_match():
    r, out = rx(["abc", "xyz", None], mode="match", pattern="^a")
    assert out["regex_match"].tolist() == [True, False, None]
    assert r.view.match_rate == 0.5


def test_split():
    r, out = rx(["a-b-c-d", "x", None], mode="split", pattern="-", split_into=3, alias="p")
    assert out[["p_1", "p_2", "p_3"]].iloc[0].tolist() == ["a", "b", "c-d"]
    assert out[["p_1", "p_2", "p_3"]].iloc[1].tolist() == ["x", None, None]
    assert out["p_1"].iloc[2] is None


def test_compile_error_is_clear():
    r, _ = rx(["a"], mode="match", pattern="(unclosed")
    assert r.status == "error" and "invalid regular expression" in r.error


@pytest.mark.parametrize("p", ["(a+)+", "(a*)*", "(a|aa)+", "(.*x)*", "(?:a+){2,}", "((a+)b)+"])
def test_catastrophic_rejected(p):
    with pytest.raises(BlockError):
        check_pattern(p)
    r, _ = rx(["aaaa"], mode="match", pattern=p)
    assert r.status == "error" and "catastrophically" in r.error


@pytest.mark.parametrize(
    "p", [r"(\d{3})+", "(foo|bar)+", r"(a+)b", r"[(a+)+]", r"\(a+\)+", "(a+)?"]
)
def test_safe_patterns_accepted(p):
    check_pattern(p)


def test_pattern_length_limit():
    with pytest.raises(ValidationError):
        graph([("b", {"type": "regex", "column": "t", "pattern": "a" * 201})], [])
    with pytest.raises(BlockError):
        check_pattern("a" * 201)


def test_long_cell_cut():
    long = "x" * 2000 + "TAIL"
    r, out = rx([long, "short TAIL"], mode="match", pattern="TAIL")
    assert out["regex_match"].tolist() == [False, True]
    assert r.view.n_truncated == 1 and any("2000" in w for w in r.warnings)
