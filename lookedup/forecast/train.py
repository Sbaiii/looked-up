"""Training for the Phase 4 models (docs/prereg_phase4.md): random search on validation, LightGBM with
monotone constraints and class weights, Platt calibration, small text model files plus models.json."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, mean_absolute_error

from lookedup.forecast.features import CATEGORICAL, FEATURES, MONOTONE_UP

log = logging.getLogger(__name__)

SEED = 20261010
TRIALS = 50
TRAIN_END = datetime(2026, 9, 10)
VALID_END = datetime(2026, 9, 20)
TEST_END = datetime(2026, 10, 7)
TARGETS = {"international": ("reach_international", 5), "planetary": ("reach_planetary", 20)}
OFFSETS = (0, 1, 3)
M2_TARGETS = ("excess_next24", "fade_hours")


# ---------------------------------------------------------------- data

@dataclass
class Encoder:
    """Categorical vocabularies from training rows; unknown values become NaN (LightGBM's missing)."""
    vocab: dict[str, list[str]] = field(default_factory=dict)
    features: list[str] = field(default_factory=lambda: list(FEATURES))

    @classmethod
    def fit(cls, rows: list[dict], features: list[str] | None = None) -> Encoder:
        feats = list(features or FEATURES)
        return cls({c: sorted({str(r[c]) for r in rows}) for c in CATEGORICAL if c in feats}, feats)

    def matrix(self, rows: list[dict]) -> np.ndarray:
        idx = {c: {v: i for i, v in enumerate(vs)} for c, vs in self.vocab.items()}
        X = np.full((len(rows), len(self.features)), np.nan)
        for i, r in enumerate(rows):
            for j, f in enumerate(self.features):
                v = r.get(f)
                if f in idx:
                    X[i, j] = idx[f].get(str(v), np.nan)
                elif v is not None:
                    X[i, j] = float(v)
        return X

    @property
    def categorical(self) -> list[int]:
        return [j for j, f in enumerate(self.features) if f in self.vocab]

    @property
    def monotone(self) -> list[int]:
        return [1 if f in MONOTONE_UP else 0 for f in self.features]

    def to_json(self) -> dict:
        return {"features": self.features, "vocab": self.vocab}

    @classmethod
    def from_json(cls, d: dict) -> Encoder:
        return cls(d["vocab"], d["features"])


def split(rows: list[dict]) -> dict[str, list[dict]]:
    """Chronological split of snapshot rows into train, validation and test by event start."""
    out = {"train": [], "valid": [], "test": []}
    for r in rows:
        s = r["start_hour"]
        if s < TRAIN_END:
            out["train"].append(r)
        elif s < VALID_END:
            out["valid"].append(r)
        elif s < TEST_END:
            out["test"].append(r)
    return out


def m1_rows(rows: list[dict], target: str, offset: int) -> list[dict]:
    """Snapshots at ``offset`` that have not yet reached the target's tier (the only useful forecasts)."""
    _, threshold = TARGETS[target]
    return [r for r in rows if r["offset_h"] == offset and r["breadth_t"] < threshold]


def m2_rows(rows: list[dict], target: str) -> list[dict]:
    """Rows for an M2 target: the t0 + 3 h snapshots, and only those with an observable fade for ``fade_hours``."""
    rows = [r for r in rows if r["offset_h"] == 3]
    return [r for r in rows if r["fade_observable"]] if target == "fade_hours" else rows


def labels(rows: list[dict], target: str) -> np.ndarray:
    """Target vector: binary tier labels as they are, counts as log1p."""
    if target in TARGETS:
        return np.array([r[TARGETS[target][0]] for r in rows], dtype=float)
    return np.log1p(np.array([max(r[target] or 0, 0) for r in rows], dtype=float))


# ---------------------------------------------------------------- models

def sample_params(rng: np.random.Generator) -> dict:
    """One random LightGBM configuration from the pre-registered search space."""
    return {"num_leaves": int(rng.integers(7, 64)), "learning_rate": float(math.exp(rng.uniform(math.log(0.02), math.log(0.2)))),
            "n_estimators": int(rng.integers(100, 801)), "min_child_samples": int(rng.integers(20, 201)),
            "feature_fraction": float(rng.uniform(0.6, 1.0)), "lambda_l2": float(rng.uniform(0, 10))}


def fit(X: np.ndarray, y: np.ndarray, enc: Encoder, params: dict, kind: str) -> lgb.Booster:
    """Fit a LightGBM booster, binary (with class weighting) or regression, with the monotone constraints of ``enc``."""
    p = dict(params)
    rounds = p.pop("n_estimators")
    base = {"verbosity": -1, "seed": SEED, "deterministic": True, "num_threads": 4,
            "monotone_constraints": enc.monotone, "monotone_constraints_method": "basic"}
    if kind == "binary":
        pos = max(float(y.sum()), 1.0)
        base |= {"objective": "binary", "scale_pos_weight": (len(y) - pos) / pos}
    else:
        base |= {"objective": "regression"}
    ds = lgb.Dataset(X, y, feature_name=enc.features, categorical_feature=enc.categorical, free_raw_data=False)
    return lgb.train(base | p, ds, num_boost_round=rounds)


def score(model: lgb.Booster, X: np.ndarray) -> np.ndarray:
    """Raw model predictions for ``X``."""
    return model.predict(X)


def logit(p: np.ndarray) -> np.ndarray:
    """Log-odds of probabilities, clipped away from 0 and 1."""
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def platt(raw_valid: np.ndarray, y_valid: np.ndarray) -> tuple[float, float]:
    """Platt scaling fitted on validation predictions: returns (slope, intercept) in logit space."""
    lr = LogisticRegression(C=1e6, max_iter=1000).fit(logit(raw_valid).reshape(-1, 1), y_valid)
    return float(lr.coef_[0][0]), float(lr.intercept_[0])


def calibrate(raw: np.ndarray, ab: tuple[float, float]) -> np.ndarray:
    """Apply Platt parameters ``ab`` to raw probabilities."""
    a, b = ab
    return 1 / (1 + np.exp(-(a * logit(raw) + b)))


def search(train: list[dict], valid: list[dict], target: str, enc: Encoder, trials: int = TRIALS) -> tuple[dict, float]:
    """Pre-registered random search: PR AUC on validation (M1) or MAE on log1p (M2)."""
    kind = "binary" if target in TARGETS else "regression"
    Xtr, ytr, Xva, yva = enc.matrix(train), labels(train, target), enc.matrix(valid), labels(valid, target)
    rng = np.random.default_rng(SEED)
    best, best_val = None, None
    for i in range(trials):
        params = sample_params(rng)
        m = fit(Xtr, ytr, enc, params, kind)
        pv = score(m, Xva)
        val = average_precision_score(yva, pv) if kind == "binary" else -mean_absolute_error(yva, pv)
        if best_val is None or val > best_val:
            best, best_val = params, val
    log.info("search %s: best validation %.4f with %s", target, best_val, best)
    return best, float(best_val if kind == "binary" else -best_val)


# ---------------------------------------------------------------- persistence

def save(model: lgb.Booster, path: Path) -> int:
    """Write a booster as text; returns the file size."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_to_string())
    return path.stat().st_size


def load(path: Path) -> lgb.Booster:
    """Read a booster written by :func:`save`."""
    return lgb.Booster(model_str=path.read_text())


def write_manifest(path: Path, manifest: dict) -> None:
    """Write the models manifest (parameters, calibration, metrics) as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=1, default=str))
