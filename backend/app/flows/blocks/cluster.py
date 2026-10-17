"""cluster: k-means on standardised numeric features. Always exploratory."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from app.flows.blocks._common import BlockError, BlockOutput, Ctx, fnum, require, to_float
from app.flows.schemas import ClusterConfig, ClusterView, Metric

SILHOUETTE_ROWS = 5_000
_CHUNK = 20
MAX_ITER = 300


def run(cfg: ClusterConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    df = inputs["in"]
    require(df, list(cfg.features), "feature")
    x = pd.DataFrame({f: to_float(df[f], f) for f in cfg.features})
    ok = x.notna().all(axis=1)
    dropped = int((~ok).sum())
    data = x[ok]
    if len(data) < cfg.k:
        raise BlockError(f"need at least k = {cfg.k} complete rows, got {len(data)}")
    scaler = StandardScaler()
    z = scaler.fit_transform(data.to_numpy())
    ctx.check()
    km = KMeans(n_clusters=cfg.k, n_init=1, max_iter=_CHUNK, random_state=cfg.seed).fit(z)
    done = _CHUNK
    while km.n_iter_ >= _CHUNK and done < MAX_ITER:  # warm-started chunks, deadline between
        ctx.check()
        km = KMeans(n_clusters=cfg.k, init=km.cluster_centers_, n_init=1, max_iter=_CHUNK).fit(z)
        done += _CHUNK
    labels = km.labels_
    centres = scaler.inverse_transform(km.cluster_centers_)
    sil = None
    if len(np.unique(labels)) > 1 and len(z) > cfg.k:
        rng = np.random.default_rng(cfg.seed)
        idx = (
            rng.choice(len(z), SILHOUETTE_ROWS, replace=False)
            if len(z) > SILHOUETTE_ROWS
            else np.arange(len(z))
        )
        if len(np.unique(labels[idx])) > 1:
            sil = fnum(silhouette_score(z[idx], labels[idx]))
    out = df[ok].reset_index(drop=True)
    out["cluster"] = labels.astype(int)
    view = ClusterView(
        k=cfg.k,
        sizes=[int((labels == i).sum()) for i in range(cfg.k)],
        centroids=[{f: fnum(v) for f, v in zip(cfg.features, c, strict=True)} for c in centres],
        metrics=[Metric(name="silhouette", value=sil)],
        dropped_missing=dropped,
    )
    warnings = [f"{dropped} rows with a missing feature dropped"] if dropped else []
    return BlockOutput(frames={"out": out}, view=view, warnings=warnings)
