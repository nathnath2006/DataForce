"""model: linear / logistic regression, SVM or SVR fitted on `train`, evaluated on `test`.

Preprocessing: numeric (and boolean) features are standardised on train; other features are
one-hot encoded (the 30 most frequent train values, the rest grouped as "other"). Rows with a
missing target or feature are dropped and counted. Coefficients are on standardised numerics
and are associations, not causes (an RBF SVM has none). Verification follows
docs/M2A-CONTRACT.md section 3.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit  # noqa: F401
from scipy.stats import rankdata
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.svm import SVC, SVR

from app.flows.blocks._common import (
    BlockError,
    BlockOutput,
    Ctx,
    dtype_of,
    fnum,
    is_numeric_kind,
    matches,
    require,
    to_float,
)
from app.flows.schemas import Metric, ModelConfig, ModelView
from app.stats.intervals import wilson

TOP_VALUES = 30
MAX_RESAMPLES = 1000
_CELLS = 4_000_000


MAX_ENCODED = 500
MAX_SVM_ROWS = 20_000  # SVM training is O(n^2)
MAX_EXPORTED_SV = 2_000  # support vectors are training rows: keep the run payload small
REGRESSION = ("linear_regression", "svr")
LEAK = "test rows may overlap the training rows: connect train and test from the same split block"
MULTIPLIED = "rows were duplicated by an upstream join, so n is inflated"


def _lst(a: Any) -> list[float | None]:
    return [fnum(x) for x in np.ravel(a)]


def _feature_spec(ct: ColumnTransformer, num: list[str], cat: list[str]) -> dict[str, Any]:
    """The preprocessing in plain data: enough to rebuild the design matrix without pickle."""
    sc = ct.named_transformers_["num"]
    mean = _lst(sc.mean_) if num else []
    std = _lst(sc.scale_) if num else []
    cats = ct.named_transformers_["cat"].categories_ if cat else []
    return {
        "numeric": [
            {"name": f, "mean": m, "std": s} for f, m, s in zip(num, mean, std, strict=True)
        ],
        "categorical": [
            {"name": f, "categories": [str(c) for c in cs], "other_label": "other"}
            for f, cs in zip(cat, cats, strict=True)
        ],
    }


def _svm_params(mdl: Any, cfg: ModelConfig, warnings: list[str]) -> dict[str, Any]:
    """decision(x) = sum_i dual_coef_i * K(support_vector_i, x) + intercept, K the kernel.

    A linear kernel collapses to one weight per feature. An RBF model needs its support vectors,
    which are training rows: above MAX_EXPORTED_SV they are left out (payload size), and the
    parameters say the model cannot be rebuilt from them.
    """
    n_sv = int(mdl.support_vectors_.shape[0])
    p: dict[str, Any] = {
        "kernel": cfg.kernel,
        "C": cfg.C,
        "gamma": float(mdl._gamma),  # noqa: SLF001 (the resolved value of "scale")
        "intercept": float(mdl.intercept_[0]),
        "n_support_vectors": n_sv,
    }
    if cfg.kernel == "linear":
        p["coef"] = _lst(mdl.coef_[0])
    if n_sv <= MAX_EXPORTED_SV:
        p["support_vectors"] = [_lst(r) for r in mdl.support_vectors_]
        p["dual_coef"] = _lst(mdl.dual_coef_)
    else:
        p["exportable"] = cfg.kernel == "linear"
        warnings.append(
            f"{n_sv} support vectors (> {MAX_EXPORTED_SV}) are not exported"
            + ("" if cfg.kernel == "linear" else ": this RBF model cannot be saved for scoring")
        )
    return p


def _resample_idx(n: int, b: int, rng: np.random.Generator, ctx: Ctx):
    step = max(1, _CELLS // max(n, 1))
    for s in range(0, b, step):
        ctx.check()
        yield rng.integers(0, n, size=(min(step, b - s), n))


def _ci(vals: np.ndarray, conf: float) -> tuple[float | None, float | None]:
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return None, None
    a = (1 - conf) / 2
    lo, hi = np.quantile(vals, [a, 1 - a])
    return float(lo), float(hi)


def _boot_regression(
    y: np.ndarray, pred: np.ndarray, b: int, conf: float, rng: np.random.Generator, ctx: Ctx
) -> dict[str, tuple[float | None, float | None]]:
    r2s, maes = [], []
    for idx in _resample_idx(len(y), b, rng, ctx):
        yt, pr = y[idx], pred[idx]
        ss_res = ((yt - pr) ** 2).sum(axis=1)
        ss_tot = ((yt - yt.mean(axis=1, keepdims=True)) ** 2).sum(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            r2s.append(np.where(ss_tot > 0, 1 - ss_res / ss_tot, np.nan))
        maes.append(np.abs(yt - pr).mean(axis=1))
    return {"r2": _ci(np.concatenate(r2s), conf), "mae": _ci(np.concatenate(maes), conf)}


def _boot_auc(
    y: np.ndarray, score: np.ndarray, b: int, conf: float, rng: np.random.Generator, ctx: Ctx
) -> tuple[float | None, float | None]:
    out = []
    for idx in _resample_idx(len(y), b, rng, ctx):
        yt, sc = y[idx], score[idx]
        ranks = rankdata(sc, axis=1)
        npos = yt.sum(axis=1)
        nneg = yt.shape[1] - npos
        with np.errstate(divide="ignore", invalid="ignore"):
            auc = ((ranks * yt).sum(axis=1) - npos * (npos + 1) / 2) / (npos * nneg)
        out.append(np.where((npos > 0) & (nneg > 0), auc, np.nan))
    return _ci(np.concatenate(out), conf)


def _clean_frame(
    df: pd.DataFrame, cfg: ModelConfig, kinds: dict[str, str]
) -> tuple[pd.DataFrame, pd.Series | None]:
    """Rows with all features and a valid target; returns (frame, target series)."""
    ok = df[cfg.features].notna().all(axis=1) & df[cfg.target].notna()
    if cfg.kind in REGRESSION:
        yv = to_float(df[cfg.target], cfg.target)
        ok &= yv.notna()
        for f in cfg.features:
            if is_numeric_kind(kinds[f]):
                ok &= to_float(df[f], f).notna()
    return df[ok].reset_index(drop=True), None


def run(cfg: ModelConfig, inputs: dict[str, pd.DataFrame], ctx: Ctx) -> BlockOutput:
    gc = ctx.gates
    train_raw, test_raw = inputs["train"], inputs["test"]
    for d in (train_raw, test_raw):
        require(d, [cfg.target, *cfg.features])
    if cfg.target in cfg.features:
        raise BlockError("the target cannot also be a feature")
    kinds = {f: dtype_of(train_raw[f]) for f in cfg.features}
    train, _ = _clean_frame(train_raw, cfg, kinds)
    test, _ = _clean_frame(test_raw, cfg, kinds)
    dropped = (len(train_raw) - len(train)) + (len(test_raw) - len(test))
    warnings = [f"{dropped} rows with a missing target or feature dropped"] if dropped else []
    if len(train) < 2:
        raise BlockError("not enough training rows after dropping missing values")
    if cfg.kind in ("svm", "svr") and len(train) > MAX_SVM_ROWS:
        train = train.sample(n=MAX_SVM_ROWS, random_state=gc.random_seed).sort_index()
        train = train.reset_index(drop=True)
        warnings.append(
            f"SVM training rows capped at {MAX_SVM_ROWS} (random sample): training is quadratic"
        )

    num = [f for f in cfg.features if kinds[f] in ("number", "integer", "boolean")]
    cat = [f for f in cfg.features if f not in num]

    def numeric(d: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=d.index)
        for f in num:
            col = d[f]
            out[f] = col.astype(float) if kinds[f] == "boolean" else to_float(col, f)
        return out

    top = {f: set(train[f].astype(str).value_counts().index[:TOP_VALUES]) for f in cat}

    def design(d: pd.DataFrame) -> pd.DataFrame:
        out = numeric(d)
        for f in cat:
            s = d[f].astype(str)
            out[f] = s.where(s.isin(top[f]), "other")
        return out

    width = len(num) + sum(min(len(top[f]) + 1, train[f].nunique() + 1) for f in cat)
    if width > MAX_ENCODED:
        raise BlockError(
            f"too many encoded features ({width} > {MAX_ENCODED}): use fewer categorical columns"
        )
    ctx.check()
    xtr, xte = design(train), design(test)
    ct = ColumnTransformer(
        [
            ("num", StandardScaler(), num),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), cat),
        ]
    )
    a_tr = ct.fit_transform(xtr)
    a_te = ct.transform(xte) if len(test) else np.empty((0, a_tr.shape[1]))
    names = list(num)
    if cat:
        enc = ct.named_transformers_["cat"]
        for f, cats in zip(cat, enc.categories_, strict=True):
            names += [f"{f}={c}" for c in cats]

    rng = np.random.default_rng(gc.random_seed)
    b = min(MAX_RESAMPLES, gc.bootstrap_resamples)
    n_test = len(test)
    reasons: list[str] = []
    out_test = test.copy()
    metrics: list[Metric] = []
    confusion = None

    params: dict[str, Any] = {
        "kind": cfg.kind,
        "target": cfg.target,
        "features": _feature_spec(ct, num, cat),
        "encoded_features": names,
    }
    gamma_arg: float | str = cfg.gamma if cfg.gamma is not None else "scale"

    if cfg.kind in REGRESSION:
        ytr = to_float(train[cfg.target], cfg.target).to_numpy()
        yte = to_float(test[cfg.target], cfg.target).to_numpy() if n_test else np.empty(0)
        if cfg.kind == "svr":
            ym = float(ytr.mean())
            ys = float(ytr.std()) or 1.0
            mdl = SVR(kernel=cfg.kernel, C=cfg.C, gamma=gamma_arg).fit(a_tr, (ytr - ym) / ys)
            coefs = mdl.coef_[0] * ys if cfg.kernel == "linear" else None

            def predict(a: np.ndarray) -> np.ndarray:
                return mdl.predict(a) * ys + ym

            params.update(_svm_params(mdl, cfg, warnings))
            params.update({"y_mean": ym, "y_std": ys})
        else:
            mdl = LinearRegression().fit(a_tr, ytr)
            coefs = mdl.coef_
            predict = mdl.predict
            params.update({"coef": _lst(mdl.coef_), "intercept": float(mdl.intercept_)})
        pred = predict(a_te) if n_test else np.empty(0)
        out_test["prediction"] = pred
        mean = float(ytr.mean())
        if n_test:
            ss_tot = float(((yte - yte.mean()) ** 2).sum())
            ss_res = float(((yte - pred) ** 2).sum())
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else math.nan
            mae = float(np.abs(yte - pred).mean())
            rmse = float(np.sqrt(((yte - pred) ** 2).mean()))
            ci = _boot_regression(yte, pred, b, gc.confidence, rng, ctx)
            base_mae = float(np.abs(yte - mean).mean())
            base_rmse = float(np.sqrt(((yte - mean) ** 2).mean()))
        else:
            r2 = mae = rmse = base_mae = base_rmse = math.nan
            ci = {"r2": (None, None), "mae": (None, None)}
        metrics = [
            Metric(
                name="r2", value=fnum(r2), ci_low=ci["r2"][0], ci_high=ci["r2"][1], baseline=0.0
            ),
            Metric(
                name="mae",
                value=fnum(mae),
                ci_low=ci["mae"][0],
                ci_high=ci["mae"][1],
                baseline=fnum(base_mae),
            ),
            Metric(name="rmse", value=fnum(rmse), baseline=fnum(base_rmse)),
        ]
        if n_test < gc.min_n:
            reasons.append(f"test set too small (n = {n_test} < {gc.min_n})")
        lo = ci["r2"][0]
        if lo is None:
            reasons.append("R2 CI not computable")
        elif lo <= 0:
            reasons.append(f"R2 CI low {lo:.3g} <= 0 (no better than predicting the mean)")
    else:
        ytr = matches(train[cfg.target], cfg.positive_value).to_numpy(dtype=float)
        yte = matches(test[cfg.target], cfg.positive_value).to_numpy(dtype=float)
        if ytr.min() == ytr.max():
            raise BlockError("the training target has only one class; nothing to learn")
        if cfg.kind == "svm":
            mdl = SVC(kernel=cfg.kernel, C=cfg.C, gamma=gamma_arg).fit(a_tr, ytr)
            coefs = mdl.coef_[0] if cfg.kernel == "linear" else None
            # Platt scaling: a sigmoid fitted on the training decision values (optimistic on
            # training data; the verdict below uses held-out rows only)
            platt = LogisticRegression(C=1e4, max_iter=1000).fit(
                mdl.decision_function(a_tr).reshape(-1, 1), ytr
            )
            pa, pb = float(platt.coef_[0, 0]), float(platt.intercept_[0])
            params.update(_svm_params(mdl, cfg, warnings))
            params.update({"platt_a": pa, "platt_b": pb, "positive_value": cfg.positive_value})
        else:
            mdl = LogisticRegression(max_iter=1000).fit(a_tr, ytr)
            coefs = mdl.coef_[0]
            params.update(
                {
                    "coef": _lst(mdl.coef_[0]),
                    "intercept": float(mdl.intercept_[0]),
                    "positive_value": cfg.positive_value,
                }
            )
        if n_test:
            if cfg.kind == "svm":
                score = mdl.decision_function(a_te)
                prob = expit(pa * score + pb)
                cls = (score > 0).astype(int)
            else:
                prob = score = mdl.predict_proba(a_te)[:, 1]
                cls = (prob >= 0.5).astype(int)
            out_test["prediction"] = cls.astype(bool)
            out_test["probability"] = prob
            npos = int(yte.sum())
            nneg = n_test - npos
            k = int((cls == yte).sum())
            acc, alo, ahi = wilson(k, n_test, gc.confidence)
            baseline = max(npos, nneg) / n_test
            tp = int(((cls == 1) & (yte == 1)).sum())
            tn = int(((cls == 0) & (yte == 0)).sum())
            fp = int(((cls == 1) & (yte == 0)).sum())
            fn = int(((cls == 0) & (yte == 1)).sum())
            confusion = [[tn, fp], [fn, tp]]
            if npos and nneg:
                auc = float(roc_auc_score(yte, score))
                auc_ci = _boot_auc(yte, score, b, gc.confidence, rng, ctx)
            else:
                auc, auc_ci = math.nan, (None, None)
            metrics = [
                Metric(name="accuracy", value=acc, ci_low=alo, ci_high=ahi, baseline=baseline),
                Metric(
                    name="auc", value=fnum(auc), ci_low=auc_ci[0], ci_high=auc_ci[1], baseline=0.5
                ),
            ]
            if n_test < gc.min_n:
                reasons.append(f"test set too small (n = {n_test} < {gc.min_n})")
            if npos < gc.min_wins:
                reasons.append(f"only {npos} positive rows in test (< {gc.min_wins})")
            if nneg < gc.min_losses:
                reasons.append(f"only {nneg} negative rows in test (< {gc.min_losses})")
            if auc_ci[0] is None:
                reasons.append("AUC CI not computable (one class in test)")
            elif auc_ci[0] <= 0.5:
                reasons.append(f"AUC CI low {auc_ci[0]:.3f} <= 0.5 (includes chance)")
            if alo <= baseline:
                reasons.append(
                    f"accuracy CI low {alo:.3f} <= majority-class baseline {baseline:.3f}"
                )
        else:
            metrics = [Metric(name="accuracy", value=None), Metric(name="auc", value=None)]
            reasons.append(f"test set too small (n = 0 < {gc.min_n})")
    if not ctx.split_verified:
        reasons.append(LEAK)
    if ctx.rows_multiplied:
        reasons.append(MULTIPLIED)
    view = ModelView(
        model=cfg.kind,
        n_train=len(train),
        n_test=n_test,
        dropped_missing=dropped,
        metrics=metrics,
        coefficients=[]
        if coefs is None
        else [{"feature": n, "coef": fnum(c)} for n, c in zip(names, np.ravel(coefs), strict=True)],
        confusion=confusion,
        status="not_verified" if reasons else "verified",
        reasons=reasons,
    )
    return BlockOutput(frames={"out": out_test}, view=view, warnings=warnings, model_params=params)
