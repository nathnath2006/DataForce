"""Column profile of a node output frame: exact counts on the full frame (UI contract 3).

At most MAX_PROFILE_COLUMNS columns; n_unique is capped (with a flag); numeric columns get an
8-bin histogram, text and boolean columns their top values. Stops when the run deadline is hit.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from app.domain.redaction import SENSITIVE
from app.flows.blocks._common import dtype_of
from app.flows.schemas import ColumnProfile, Histogram, TopValue

MAX_PROFILE_COLUMNS = 60
MAX_UNIQUE = 10_000
HIST_BINS = 8
TOP_N = 5
VALUE_CHARS = 60
HIDDEN = "(hidden)"


def _profile_column(name: str, s: pd.Series, dtype: str) -> ColumnProfile:
    n = len(s)
    non_null = int(s.notna().sum())
    try:
        n_unique = int(s.nunique(dropna=True))
    except TypeError:  # unhashable values
        n_unique = int(s.astype(str).nunique())
    p = ColumnProfile(
        name=name,
        dtype=dtype,  # type: ignore[arg-type]
        n=n,
        non_null=non_null,
        n_unique=min(n_unique, MAX_UNIQUE),
        n_unique_capped=n_unique > MAX_UNIQUE,
    )
    if dtype in ("number", "integer"):
        x = pd.to_numeric(s, errors="coerce").to_numpy(dtype=float)
        x = x[np.isfinite(x)]
        if len(x):
            counts, _ = np.histogram(x, bins=HIST_BINS)
            p.hist = Histogram(
                min=float(x.min()), max=float(x.max()), counts=[int(c) for c in counts]
            )
    elif dtype in ("text", "boolean") and non_null:
        vc = s.dropna().astype(str).value_counts().head(TOP_N)
        hide = bool(SENSITIVE.match(name.strip()))
        p.top = [
            TopValue(value=HIDDEN if hide else str(v)[:VALUE_CHARS], count=int(c))
            for v, c in vc.items()
        ]
    return p


def profile_frame(df: pd.DataFrame, deadline: float | None = None) -> list[ColumnProfile] | None:
    """None when the run's time limit is reached before the first column is done."""
    out: list[ColumnProfile] = []
    for i in range(min(df.shape[1], MAX_PROFILE_COLUMNS)):
        if deadline is not None and time.monotonic() >= deadline:
            break
        s = df.iloc[:, i]
        out.append(_profile_column(str(df.columns[i]), s, dtype_of(s)))
    return out or None
