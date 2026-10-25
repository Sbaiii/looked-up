from __future__ import annotations

from datetime import datetime, timedelta

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


def test_logit_and_calibration_round_trip():
    p = np.array([0.01, 0.2, 0.5, 0.8, 0.99])
    assert np.allclose(T.calibrate(p, (1.0, 0.0)), p)               # identity parameters change nothing
    assert np.isfinite(T.logit(np.array([0.0, 1.0]))).all()          # clipped, never infinite
    shifted = T.calibrate(p, (1.0, 1.0))
    assert (shifted > p).all()                                      # a positive intercept raises every forecast


def test_m2_rows_use_the_three_hour_snapshot_and_observable_fades():
    rows = [{"offset_h": h, "fade_observable": f} for h in (0, 1, 3) for f in (True, False)]
    assert all(r["offset_h"] == 3 for r in T.m2_rows(rows, "excess_next24"))
    assert len(T.m2_rows(rows, "excess_next24")) == 2
    assert T.m2_rows(rows, "fade_hours") == [{"offset_h": 3, "fade_observable": True}]


def test_sampled_parameters_stay_in_the_preregistered_space():
    rng = np.random.default_rng(T.SEED)
    for _ in range(200):
        p = T.sample_params(rng)
        assert 7 <= p["num_leaves"] <= 63
        assert 0.02 <= p["learning_rate"] <= 0.2
        assert 100 <= p["n_estimators"] <= 800
        assert 20 <= p["min_child_samples"] <= 200
        assert 0.6 <= p["feature_fraction"] <= 1.0
        assert 0 <= p["lambda_l2"] <= 10


def test_m2_metrics_in_log_space_and_hours():
    y = np.log1p(np.array([0.0, 3.0, 7.0]))
    m = E.m2_metrics(y, y, hours=True)
    assert m["n"] == 3 and m["mae_log"] == 0 and m["mape_log"] == 0 and m["median_abs_error_hours"] == 0
    off = E.m2_metrics(y, y + 1)
    assert np.isclose(off["mae_log"], 1.0) and "median_abs_error_hours" not in off


def test_split_follows_the_preregistered_boundaries():
    rows = [{"start_hour": t} for t in (T.TRAIN_END - timedelta(hours=1), T.TRAIN_END, T.VALID_END, T.TEST_END)]
    sp = T.split(rows)
    assert [len(sp[k]) for k in ("train", "valid", "test")] == [1, 1, 1]       # TEST_END itself is out of every set


def test_labels_for_tiers_and_counts():
    rows = [{"reach_international": 1, "excess_next24": 0}, {"reach_international": 0, "excess_next24": np.e - 1},
            {"reach_international": 0, "excess_next24": -5}]
    assert T.labels(rows, "international").tolist() == [1.0, 0.0, 0.0]
    assert np.allclose(T.labels(rows, "excess_next24"), [0.0, 1.0, 0.0])        # negatives clipped to 0


def test_encoder_json_round_trip():
    rows = _rows(50)
    enc = T.Encoder.fit(rows)
    back = T.Encoder.from_json(enc.to_json())
    assert back.features == enc.features and back.vocab == enc.vocab
    assert np.array_equal(back.matrix(rows), enc.matrix(rows), equal_nan=True)
    assert back.monotone == enc.monotone and back.categorical == enc.categorical


def test_metrics_on_a_single_class_sample():
    y = np.zeros(20)
    s = np.linspace(0, 1, 20)
    m = E.m1_metrics(y, s)
    assert m["roc_auc"] is None and m["pr_auc"] is None and m["positives"] == 0
    assert np.isnan(E.calib_slope(y, s))
    assert np.isnan(E.lift_top10(y, s))                                  # no positives: lift is undefined


def test_m1_baselines():
    tr, te = _rows(300, seed=1), _rows(200, seed=2)
    y_tr = T.labels(tr, "international")
    y_te = T.labels(te, "international")
    out, sl = E.m1_baselines(tr, te, y_tr, y_te)
    assert out["base_rate"]["roc_auc"] == 0.5 and len(sl) == len(te)
    flagged = np.array([r["breadth_t"] >= 3 for r in te])
    tp = int((flagged & (y_te == 1)).sum())
    assert out["breadth_rule"]["rule_precision"] == tp / flagged.sum()
    assert out["breadth_rule"]["rule_recall"] == tp / y_te.sum()
    assert out["sitelinks_logistic"]["roc_auc"] > 0.6                 # fame does predict these synthetic rows

def test_fade_time_baselines():
    tr = [{"category": "death", "fade_hours": 2} for _ in range(25)] + [{"category": "sports", "fade_hours": 6}] * 5
    te = [{"category": "death", "hours_since_peak": 3}, {"category": "sports", "hours_since_peak": 100}]
    b = E.m2_baselines("fade_hours", tr, te)
    assert np.allclose(b["category_decay"], np.log1p([2, 2]))         # sports has too few rows: overall median
    assert np.allclose(b["persistence"], np.log1p([3, 48]))           # capped at 48 h

def test_fit_m1():
    rows = _rows(400)
    enc = T.Encoder.fit(rows)
    params = {"num_leaves": 7, "learning_rate": 0.2, "n_estimators": 30, "min_child_samples": 5,
              "feature_fraction": 1.0, "lambda_l2": 0.0}
    model, (a, b) = E.fit_m1(rows[:300], rows[300:], "international", params, enc)
    p = T.calibrate(T.score(model, enc.matrix(rows[300:])), (a, b))
    assert np.isfinite(a) and np.isfinite(b) and ((0 < p) & (p < 1)).all()


def test_permutation_importance_ranks_the_signal_first():
    rows = _rows(500)
    enc = T.Encoder.fit(rows)
    params = {"num_leaves": 7, "learning_rate": 0.2, "n_estimators": 40, "min_child_samples": 5,
              "feature_fraction": 1.0, "lambda_l2": 0.0}
    model = T.fit(enc.matrix(rows), T.labels(rows, "international"), enc, params, "binary")
    imp = E.permutation_importance(model, enc, rows, "international", repeats=2)
    assert len(imp) == len(enc.features)
    assert imp[0]["feature"] in {"n_sitelinks", "excess_t"}               # the two columns built from fame
    assert [d["importance"] for d in imp] == sorted((d["importance"] for d in imp), reverse=True)


def test_rolling_folds():
    base = _rows(1100, seed=3)
    rows = []
    for i, r in enumerate(base):
        start = datetime(2026, 8, 1) + timedelta(hours=1.6 * i)
        for off in (1, 3):
            rows.append(r | {"start_hour": start, "offset_h": off, "excess_hour_t": 5.0 + (i % 7)})
    params = {"num_leaves": 7, "learning_rate": 0.2, "n_estimators": 20, "min_child_samples": 5,
              "feature_fraction": 1.0, "lambda_l2": 0.0}
    folds = E.rolling(rows, params, params)
    assert [f["fold"] for f in folds] == [f"{lo}..{hi}" for lo, hi in E.FOLDS]
    assert all(0 <= f["m1_international_1h"]["roc_auc"] <= 1 and f["m2_excess"]["n"] > 0 for f in folds)


def test_search_is_reproducible():
    rows = _rows(300)
    enc = T.Encoder.fit(rows)
    a = T.search(rows[:200], rows[200:], "international", enc, trials=2)
    b = T.search(rows[:200], rows[200:], "international", enc, trials=2)
    assert a == b and 0 <= a[1] <= 1                                   # same seed, same choice; PR AUC in [0, 1]
    m2 = T.m2_rows([r | {"offset_h": 3} for r in rows], "excess_next24")
    params, mae = T.search(m2[:200], m2[200:], "excess_next24", T.Encoder.fit(m2), trials=1)
    assert mae >= 0 and set(params) == set(T.sample_params(np.random.default_rng(0)))


def test_load_rows_joins_label_and_final_breadth():
    import duckdb

    con = duckdb.connect()
    con.execute("ATTACH ':memory:' AS wh")
    con.execute("CREATE TABLE wh.main.fct_event_snapshots AS SELECT * FROM (VALUES ('a', 1, 2), ('a', 2, 4), ('b', 1, 2)) t(event_id, offset_h, breadth_t)")
    con.execute("CREATE TABLE wh.main.fct_app_events AS SELECT * FROM (VALUES ('a', 'Alpha', 7), ('c', 'Gamma', 3)) t(event_id, label_en, breadth)")
    rows = sorted(E.load_rows(con), key=lambda r: r["offset_h"])
    assert rows == [{"event_id": "a", "offset_h": 1, "breadth_t": 2, "label_en": "Alpha", "final_breadth": 7},
                    {"event_id": "a", "offset_h": 2, "breadth_t": 4, "label_en": "Alpha", "final_breadth": 7}]


def test_encoder_missing_values_are_nan():
    enc = T.Encoder({"lead_lang": ["en", "fr"]}, features=["lead_lang", "n_sitelinks"])
    X = enc.matrix([{"lead_lang": "fr", "n_sitelinks": 12}, {"lead_lang": "xx", "n_sitelinks": None}, {}])
    assert X[0].tolist() == [1.0, 12.0]
    assert np.isnan(X[1]).all() and np.isnan(X[2]).all()


def test_decay_ratios_skip_quiet_hours():
    rows = [{"category": "death", "excess_hour_t": 10.0, "excess_next24": 30.0}] * 20
    rows += [{"category": None, "excess_hour_t": 10.0, "excess_next24": 10.0}] * 3
    rows += [{"category": "sports", "excess_hour_t": 0.0, "excess_next24": 999.0}] * 25
    out = E.decay_ratios(rows)
    assert out == {"death": 3.0, "_all": 3.0}                           # sports never had a non-zero hour; "other" has 3 rows
    assert E.decay_ratios([]) == {"_all": 0.0}


def _backtest_rows(n=900, seed=3):
    rng = np.random.default_rng(seed)
    start, out = datetime(2026, 8, 1), []
    for i in range(n):
        fame = int(rng.integers(1, 30))
        big = rng.random() < fame / 30
        s = start + timedelta(hours=1.75 * i)                     # 1 Aug to 6 Oct: train, validation and test
        for off in T.OFFSETS:
            out.append({"event_id": f"E{i}", "offset_h": off, "start_hour": s, "snapshot_ts": s + timedelta(hours=off),
                        "label_en": f"Event {i}", "final_breadth": 25 if big and fame > 20 else 6 if big else 2,
                        "breadth_t": 2, "max_surprise_t": 10.0 + fame, "sum_surprise_t": 20.0, "excess_t": 100.0 * fame,
                        "lead_share_t": 0.5, "new_langs_last_hour": 0, "hours_since_start": off, "is_death": int(fame % 7 == 0),
                        "hour_utc": i % 24, "weekday": i % 7, "n_sitelinks": fame, "views_t": 10.0 * fame, "views_slope": 0.0,
                        "peak_views_so_far": 20.0, "lead_views_share": 0.5, "lead_lang": "en" if i % 3 else "es",
                        "entity_class": "human", "reach_international": int(big), "reach_planetary": int(big and fame > 20),
                        "excess_next24": 50.0 * fame + rng.random(), "fade_hours": 1 + fame % 5, "fade_observable": True,
                        "excess_hour_t": 10.0 + fame, "hours_since_peak": 1, "category": "death" if fame % 7 == 0 else "human"})
    return out


def test_backtest_run_end_to_end(tmp_path, monkeypatch):
    import json

    import pytest

    pytest.importorskip("matplotlib")
    import duckdb

    import lookedup.warehouse as W

    small = {"num_leaves": 7, "learning_rate": 0.2, "n_estimators": 20, "min_child_samples": 5, "feature_fraction": 1.0,
             "lambda_l2": 0.0}
    duckdb.connect(str(tmp_path / "w.duckdb")).close()
    monkeypatch.setattr(W, "WAREHOUSE_DB", tmp_path / "w.duckdb")
    monkeypatch.setattr(E, "load_rows", lambda con: _backtest_rows())
    monkeypatch.setattr(E.T, "search", lambda tr, va, target, enc: (small, 0.5))
    for name, value in {"OUT": tmp_path / "analysis", "FIG": tmp_path / "fig", "PARAMS_FILE": tmp_path / "params.json",
                        "DATA_DIR": tmp_path / "data"}.items():
        monkeypatch.setattr(E, name, value)
    res = E.run()
    assert set(res["split_sizes"]) == {"train", "valid", "test"} and all(res["split_sizes"].values())
    assert {"H6", "H7", "H8"} <= set(res) and res["H6"]["verdict"] in ("supported", "rejected")
    assert len(res["m1"]) == 6 and set(res["m2"]) == {"excess_next24", "fade_hours"}
    assert [e["why"] for e in res["examples"]] == ["confident hit", "false alarm", "missed", "median call", "largest attention left"]
    assert json.loads((tmp_path / "params.json").read_text())["international_t1"] == small
    assert (tmp_path / "fig" / "phase4_calibration.png").exists() and (tmp_path / "fig" / "phase4_importance.png").exists()
    assert len(list((tmp_path / "data" / "models" / "backtest").glob("*.txt"))) == 8
    assert json.loads((tmp_path / "analysis" / "phase4_metrics.json").read_text())["backtest_model_bytes"]


def test_categorical_features_are_features():
    from lookedup.forecast.features import CATEGORICAL, FEATURES, LEAKY, MONOTONE_UP

    assert set(CATEGORICAL) <= set(FEATURES) and LEAKY <= set(FEATURES) and MONOTONE_UP <= set(FEATURES)
    assert len(FEATURES) == len(set(FEATURES))


def test_split_windows_are_ordered():
    assert T.TRAIN_END < T.VALID_END < T.TEST_END


def test_identity_calibration():
    p = np.array([0.1, 0.5, 0.9])
    assert np.allclose(T.calibrate(p, (1.0, 0.0)), p)


def test_calib_curve_bins():
    y = np.array([0, 1, 1])
    p = np.array([0.05, 0.95, 1.0])
    curve = E.calib_curve(y, p)
    assert [c["bin"] for c in curve] == [0, 9] and curve[1]["n"] == 2 and curve[1]["observed"] == 1.0


def test_lift_without_positives():
    assert np.isnan(E.lift_top10(np.zeros(20), np.arange(20.0)))
