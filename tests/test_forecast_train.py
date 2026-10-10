from __future__ import annotations

from datetime import datetime

import numpy as np

from lookedup.forecast import evaluate as E
from lookedup.forecast import train as T


def _rows(n=400, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        fame = int(rng.integers(1, 30))
        b = int(rng.integers(2, 5))
        y = int(rng.random() < (fame / 30) ** 2)
        out.append({"event_id": f"E{i}", "offset_h": 1, "start_hour": datetime(2026, 8, 1), "breadth_t": b,
                    "max_surprise_t": 10.0, "sum_surprise_t": 20.0, "excess_t": 100.0 * fame, "lead_share_t": 0.5,
                    "new_langs_last_hour": 0, "hours_since_start": 2, "is_death": 0, "hour_utc": 3, "weekday": 1,
                    "n_sitelinks": fame, "views_t": 10.0, "views_slope": 0.0, "peak_views_so_far": 20.0,
                    "lead_views_share": 0.5, "lead_lang": "en" if i % 2 else "ja", "entity_class": "human",
                    "reach_international": y, "reach_planetary": 0, "excess_next24": 50.0 * fame,
                    "fade_hours": 3, "fade_observable": True, "excess_hour_t": 10.0, "hours_since_peak": 1,
                    "category": "human"})
    return out


def test_encoder_maps_categories_and_unknowns():
    enc = T.Encoder.fit(_rows(10))
    X = enc.matrix([dict(_rows(1)[0], lead_lang="xx")])
    j = enc.features.index("lead_lang")
    assert np.isnan(X[0, j]) and enc.vocab["lead_lang"] == ["en", "ja"]
    assert enc.monotone[enc.features.index("n_sitelinks")] == 1 and enc.monotone[j] == 0


def test_platt_calibration_fixes_inflated_probabilities():
    rng = np.random.default_rng(1)
    y = (rng.random(4000) < 0.1).astype(float)
    raw = np.clip(np.where(y == 1, 0.8, 0.5) + rng.normal(0, 0.1, 4000), 0.01, 0.99)   # weighted-model style
    p = T.calibrate(raw, T.platt(raw, y))
    assert abs(p.mean() - y.mean()) < 0.01
    assert 0.8 < E.calib_slope(y, p) < 1.2


def test_metrics_and_lift():
    y = np.array([0, 0, 0, 1, 1] * 20, dtype=float)
    s = np.array([0.1, 0.2, 0.3, 0.8, 0.9] * 20)
    m = E.m1_metrics(y, s)
    assert m["roc_auc"] == 1.0 and m["lift_top10"] == 2.5
    assert sum(b["n"] for b in E.calib_curve(y, s)) == 100


def test_fame_model_learns_and_saves_small(tmp_path):
    rows = _rows()
    enc = T.Encoder.fit(rows)
    params = {"num_leaves": 7, "learning_rate": 0.1, "n_estimators": 50, "min_child_samples": 20,
              "feature_fraction": 1.0, "lambda_l2": 0.0}
    m = T.fit(enc.matrix(rows), T.labels(rows, "international"), enc, params, "binary")
    p = T.score(m, enc.matrix(rows))
    assert E.m1_metrics(T.labels(rows, "international"), p, prob=False)["roc_auc"] > 0.8
    assert T.save(m, tmp_path / "m.txt") < 5_000_000
    assert np.allclose(T.score(T.load(tmp_path / "m.txt"), enc.matrix(rows)), p)


def test_category_decay_baseline():
    rows = _rows(60)
    pred = E.m2_baselines("excess_next24", rows, rows[:3])["category_decay"]
    ratios = E.decay_ratios(rows)
    assert np.allclose(pred, np.log1p([10.0 * ratios["human"]] * 3))
