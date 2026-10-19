"""Apply a saved model's plain-JSON parameters to a DataFrame. Pure: no database, no pickle.

The design matrix is rebuilt exactly as the model block built it for training: numeric columns
(x - mean) / std with a missing value replaced by the mean, categorical columns one-hot on the saved
categories (a value never seen in training counts as "other", which is all zeros when training had
no "other" column). Classification thresholds follow the block: logistic probability >= 0.5, SVM
decision value > 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit

CHUNK_ROWS = 2_000  # rows per kernel block: bounds the memory of the RBF sum


_CHUNK = 5_000  # rows per distance block


PROBABILITY_CAVEAT = (
    "probabilities are calibrated estimates; the verdict covers ranking and accuracy, "
    "not probability calibration"
)
IMPUTED_NOTE = (
    "{n} rows had a missing numeric feature, replaced by the training mean: the model's verdict "
    "does not cover them (it was checked on complete rows only); see score_imputed"
)


class ScoringError(Exception):
    """The saved model cannot be applied to this table. The message is shown to the user."""


@dataclass(frozen=True)
class ModelSnapshot:
    id: str
    name: str
    kind: str  # linear | logistic | svm | svr | kmeans
    params: dict[str, Any]
    features: list[str]
    status: str  # verified | not_verified | exploratory


@dataclass
class ScoreResult:
    columns: pd.DataFrame  # same index as the input
    n_imputed: int = 0  # rows with a missing numeric feature (supervised models)
    n_unscored: int = 0  # rows left null (k-means with a missing feature)
    notes: list[str] = field(default_factory=list)


def feature_columns(kind: str, params: dict[str, Any]) -> list[str]:
    if kind == "kmeans":
        return [str(f) for f in params["features"]]
    spec = params["features"]
    return [f["name"] for f in spec["numeric"]] + [f["name"] for f in spec["categorical"]]


def _numeric(col: pd.Series, name: str) -> np.ndarray:
    if pd.api.types.is_bool_dtype(col.dtype):
        return col.astype(float).to_numpy()
    out = pd.to_numeric(col, errors="coerce").astype("float64").to_numpy(copy=True)
    out[~np.isfinite(out)] = np.nan
    return out


def design_matrix(df: pd.DataFrame, params: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """(matrix, boolean mask of rows with an imputed numeric value)."""
    spec = params["features"]
    n = len(df)
    parts: list[np.ndarray] = []
    imputed = np.zeros(n, dtype=bool)
    for f in spec["numeric"]:
        x = _numeric(df[f["name"]], f["name"])
        miss = np.isnan(x)
        imputed |= miss
        mean, std = float(f["mean"]), float(f["std"]) or 1.0
        x = np.where(miss, mean, x)
        parts.append(((x - mean) / std).reshape(-1, 1))
    for f in spec["categorical"]:
        cats = list(f["categories"])
        index = {c: i for i, c in enumerate(cats)}
        other = index.get(f.get("other_label", "other"))
        block = np.zeros((n, len(cats)))
        for r, v in enumerate(df[f["name"]].astype(str).to_numpy()):
            j = index.get(v, other)
            if j is not None:
                block[r, j] = 1.0
        parts.append(block)
    if not parts:
        return np.zeros((n, 0)), imputed
    return np.hstack(parts), imputed


def _svm_decision(a: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    if p.get("kernel") == "linear" and "coef" in p:
        return a @ np.asarray(p["coef"], dtype=float) + float(p["intercept"])
    if "support_vectors" not in p or "dual_coef" not in p:
        raise ScoringError("this model was saved without its support vectors and cannot be applied")
    sv = np.asarray(p["support_vectors"], dtype=float)
    dual = np.asarray(p["dual_coef"], dtype=float)
    gamma = float(p["gamma"])
    sv_sq = (sv**2).sum(axis=1)
    out = np.empty(len(a))
    for s in range(0, len(a), CHUNK_ROWS):
        blk = a[s : s + CHUNK_ROWS]
        d2 = (blk**2).sum(axis=1)[:, None] + sv_sq[None, :] - 2.0 * blk @ sv.T
        out[s : s + CHUNK_ROWS] = np.exp(-gamma * np.maximum(d2, 0.0)) @ dual + float(
            p["intercept"]
        )
    return out


def score_frame(model: ModelSnapshot, df: pd.DataFrame) -> ScoreResult:
    """Score columns for `df`: `score` always; `score_class` for a classifier; k-means adds
    `score_distance` (distance to the centroid, in standardised units).

    Saved parameters come from the server's own runs; parameters that do not fit (a shape
    mismatch, a missing key) still give a clear ScoringError, never an unhandled error."""
    try:
        return _score_frame(model, df)
    except ScoringError:
        raise
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise ScoringError(
            f"the saved parameters do not fit this model ({type(exc).__name__})"
        ) from None


def _score_frame(model: ModelSnapshot, df: pd.DataFrame) -> ScoreResult:
    p = model.params
    need = feature_columns(model.kind, p)
    missing = [c for c in need if c not in df.columns]
    if missing:
        shown = ", ".join(f"'{c}'" for c in missing[:10])
        raise ScoringError(f"the input is missing the model's feature column(s): {shown}")
    idx = df.index
    if model.kind == "kmeans":
        x = np.column_stack([_numeric(df[f], f) for f in need]) if len(df) else np.empty((0, 0))
        ok = ~np.isnan(x).any(axis=1) if len(df) else np.zeros(0, dtype=bool)
        mean = np.asarray(p["scaler_mean"], dtype=float)
        std = np.asarray(p["scaler_std"], dtype=float)
        cent = np.asarray(p["centroids_scaled"], dtype=float)
        z = (x[ok] - mean) / np.where(std == 0, 1.0, std)
        label = np.full(len(df), np.nan)
        dist = np.full(len(df), np.nan)
        if len(z):
            # in chunks: rows x centroids x features at once could take gigabytes
            lab, dmin = np.empty(len(z)), np.empty(len(z))
            for s0 in range(0, len(z), _CHUNK):
                d2 = ((z[s0 : s0 + _CHUNK, None, :] - cent[None, :, :]) ** 2).sum(axis=2)
                lab[s0 : s0 + _CHUNK] = d2.argmin(axis=1)
                dmin[s0 : s0 + _CHUNK] = np.sqrt(d2.min(axis=1))
            label[ok], dist[ok] = lab, dmin
        cols = pd.DataFrame(
            {"score": pd.array(label, dtype="Int64"), "score_distance": dist}, index=idx
        )
        res = ScoreResult(cols, n_unscored=int((~ok).sum()))
        if res.n_unscored:
            res.notes.append(f"{res.n_unscored} rows with a missing feature have no cluster")
        return res
    a, imputed = design_matrix(df, p)
    n_imputed = int(imputed.sum())
    kind = model.kind
    cols = pd.DataFrame(index=idx)
    if kind == "linear":
        cols["score"] = a @ np.asarray(p["coef"], dtype=float) + float(p["intercept"])
    elif kind == "logistic":
        prob = expit(a @ np.asarray(p["coef"], dtype=float) + float(p["intercept"]))
        cols["score"], cols["score_class"] = prob, prob >= 0.5
    elif kind == "svm":
        dec = _svm_decision(a, p)
        cols["score"] = expit(float(p["platt_a"]) * dec + float(p["platt_b"]))
        cols["score_class"] = dec > 0
    elif kind == "svr":
        cols["score"] = _svm_decision(a, p) * float(p["y_std"]) + float(p["y_mean"])
    else:
        raise ScoringError(f"unknown model kind '{kind}'")
    cols["score_imputed"] = imputed
    res = ScoreResult(cols, n_imputed=n_imputed)
    if kind == "svm":
        res.notes.append(PROBABILITY_CAVEAT)
    if n_imputed:
        res.notes.append(IMPUTED_NOTE.format(n=n_imputed))
    return res
