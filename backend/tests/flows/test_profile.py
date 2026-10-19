from __future__ import annotations

import time

import numpy as np
import pandas as pd

from app.flows.profile import MAX_PROFILE_COLUMNS, MAX_UNIQUE, profile_frame

from .helpers import ds, run


def test_counts_nulls_hist_and_top():
    df = pd.DataFrame(
        {
            "amt": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, None, None],
            "city": ["a", "a", "b", None, "c", "c", "c", "d", "e", "f"],
            "ok": [True, False, True, True, True, False, True, True, True, True],
        }
    )
    p = {c.name: c for c in profile_frame(df) or []}
    assert (p["amt"].n, p["amt"].non_null, p["amt"].n_unique) == (10, 8, 8)
    h = p["amt"].hist
    assert h and (h.min, h.max) == (0.0, 8.0) and sum(h.counts) == 8 and len(h.counts) == 8
    assert p["city"].non_null == 9 and p["city"].hist is None
    assert p["city"].top and p["city"].top[0].value == "c" and p["city"].top[0].count == 3
    assert len(p["city"].top) == 5
    assert p["ok"].top and p["ok"].top[0].value == "True"


def test_caps():
    wide = pd.DataFrame({f"c{i}": [1, 2] for i in range(70)})
    assert len(profile_frame(wide) or []) == MAX_PROFILE_COLUMNS
    big = pd.DataFrame({"u": np.arange(MAX_UNIQUE + 5).astype(str)})
    p = (profile_frame(big) or [])[0]
    assert p.n_unique == MAX_UNIQUE and p.n_unique_capped and p.n == MAX_UNIQUE + 5
    long = pd.DataFrame({"t": ["x" * 200]})
    top = (profile_frame(long) or [])[0].top
    assert top and len(top[0].value) == 60


def test_non_numeric_and_empty():
    d = pd.DataFrame({"d": pd.to_datetime(["2024-01-01", None])})
    p = (profile_frame(d) or [])[0]
    assert p.hist is None and p.top is None and p.non_null == 1
    e = (profile_frame(pd.DataFrame({"a": pd.Series([], dtype=float)})) or [])[0]
    assert (e.n, e.non_null, e.n_unique, e.hist) == (0, 0, 0, None)
    assert profile_frame(pd.DataFrame()) is None


def test_deadline_respected():
    df = pd.DataFrame({"a": [1], "b": [2]})
    assert profile_frame(df, deadline=time.monotonic() - 1) is None


def test_engine_attaches_profile():
    df = pd.DataFrame({"x": [1, 2, 3], "y": ["a", "b", "b"]})
    r = run({"deals": df}, [("d", ds())], [])["d"]
    assert r.profile and r.profile[0].non_null == 3
    assert r.profile[1].top and r.profile[1].top[0].value == "b"
