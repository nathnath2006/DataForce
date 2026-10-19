"""Deadline-aware percentile bootstrap of the median for the stats block."""

from __future__ import annotations

import numpy as np

from app.flows.blocks._common import Ctx
from app.stats.intervals import percentile_interval as interval  # noqa: F401 (re-exported)

_CHUNK_CELLS = 2_000_000


def boot_medians(values: np.ndarray, resamples: int, rng: np.random.Generator, ctx: Ctx):
    n = values.size
    out = np.empty(resamples)
    step = max(1, _CHUNK_CELLS // max(n, 1))
    for start in range(0, resamples, step):
        ctx.check()
        m = min(step, resamples - start)
        idx = rng.integers(0, n, size=(m, n))
        out[start : start + m] = np.median(values[idx], axis=1)
    return out
