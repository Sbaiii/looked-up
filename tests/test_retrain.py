"""The weekly forecast retrain (ADR 0029) on a small synthetic training set in a local lake."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from lookedup.forecast import retrain as R
from lookedup.forecast import train as T
from lookedup.store import LocalStore, Manifest

SMALL = {"num_leaves": 7, "learning_rate": 0.2, "n_estimators": 20, "min_child_samples": 5, "feature_fraction": 1.0,
         "lambda_l2": 0.0}


def _rows(n=600, seed=1):
    rng = np.random.default_rng(seed)
    out = []
    start = datetime(2026, 9, 1)
    for i in range(n):
        fame = int(rng.integers(1, 30))
        big = rng.random() < fame / 30
        for off in T.OFFSETS:
            out.append({"event_id": f"E{i}", "offset_h": off, "start_hour": start + timedelta(hours=2 * i),
                        "breadth_t": 2, "max_surprise_t": 10.0 + fame, "sum_surprise_t": 20.0, "excess_t": 100.0 * fame,
                        "lead_share_t": 0.5, "new_langs_last_hour": 0, "hours_since_start": off, "is_death": 0,
                        "hour_utc": i % 24, "weekday": i % 7, "n_sitelinks": fame, "views_t": 10.0 * fame,
                        "views_slope": 0.0, "peak_views_so_far": 20.0, "lead_views_share": 0.5, "lead_lang": "en",
                        "entity_class": "human", "reach_international": int(big), "reach_planetary": int(big and fame > 22),
                        "excess_next24": 50.0 * fame, "fade_hours": 3, "fade_observable": True, "excess_hour_t": 10.0,
                        "hours_since_peak": 1, "category": "human"})
    return out


def test_backtest_summary():
    s = R.backtest_summary()
    assert s["auc_international_t1"] == 0.875 and s["test_window"] == ["2026-09-20", "2026-10-06"]
    assert s["calibration_curve"] and 0 < s["base_rate_international_t1"] < 1


def test_retrain_needs_training_data(tmp_path):
    with pytest.raises(RuntimeError, match="no training data"):
        R.retrain(LocalStore(tmp_path / "lake"), now=datetime(2026, 10, 12), add_live_week=False)


def _params(tmp_path, monkeypatch):
    params = tmp_path / "params.json"
    params.write_text(json.dumps({k: SMALL for k in [f"{t}_t{o}" for t in T.TARGETS for o in T.OFFSETS]
                                  + [f"m2_{t}" for t in T.M2_TARGETS]}))
    monkeypatch.setattr(R, "PARAMS", params)


def test_retrain_publishes_models_and_manifest(tmp_path, monkeypatch):
    _params(tmp_path, monkeypatch)
    store = LocalStore(tmp_path / "lake")
    batch = tmp_path / "batch.parquet"
    pq.write_table(pa.Table.from_pylist(_rows()), batch)
    store.commit({f"{R.TRAINING}/batch.parquet": batch}, Manifest(), "seed: the batch training table")
    res = R.retrain(store, now=datetime(2026, 10, 12), add_live_week=False)
    assert res["version"] == "2026-10-12" and res["rows"] == 1800 and len(res["bytes"]) == 8
    manifest = json.loads((tmp_path / "lake" / R.MANIFEST).read_text())
    assert set(manifest["models"]) == set(res["bytes"]) and manifest["backtest"]["auc_international_t1"] == 0.875
    assert all((tmp_path / "lake" / R.MODELS_PREFIX / s["file"]).exists() for s in manifest["models"].values())


def test_live_week_without_files(tmp_path):
    from datetime import date

    assert R.live_week(LocalStore(tmp_path / "lake"), date(2026, 10, 12), tmp_path) is None


def test_calibration_window_widens_for_rare_targets():
    rows = _rows()
    cutoff = max(r["start_hour"] for r in rows) + timedelta(hours=1)
    params = {k: SMALL for k in [f"{t}_t{o}" for t in T.TARGETS for o in T.OFFSETS] + [f"m2_{t}" for t in T.M2_TARGETS]}
    _, specs = R.train_all(rows, params, cutoff)
    assert all(s["calibration_positives"] >= 5 for s in specs.values() if s["kind"] == "m1")
    assert specs["planetary_t0"]["calibration_days"] >= specs["international_t0"]["calibration_days"]
    assert specs["m2_excess_next24"]["platt"] is None


def test_live_week_skipped_before_production(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(R, "live_week", lambda *a: called.append(a))
    with pytest.raises(RuntimeError, match="no training data"):
        R.retrain(LocalStore(tmp_path / "lake"), now=datetime(2026, 10, 9))     # last full week ends before 7 Oct
    assert called == []


def test_batch_table_stops_at_production(tmp_path, monkeypatch):
    import duckdb

    import lookedup.warehouse as W
    from lookedup import db

    wh = tmp_path / "w.duckdb"
    con = duckdb.connect(str(wh))
    con.execute("""CREATE TABLE fct_event_snapshots AS SELECT * FROM (VALUES
        ('a', TIMESTAMP '2026-10-06 23:00'), ('b', TIMESTAMP '2026-10-07 00:00'), ('c', TIMESTAMP '2026-09-01 08:00'))
        t(event_id, start_hour)""")
    con.close()
    monkeypatch.setattr(W, "WAREHOUSE_DB", wh)
    assert sorted(R.batch_table(db.connect())["event_id"].to_pylist()) == ["a", "c"]


def test_retrain_uploads_the_batch_once(tmp_path, monkeypatch):
    _params(tmp_path, monkeypatch)
    monkeypatch.setattr(R, "batch_table", lambda con: pa.Table.from_pylist(_rows()))
    store = LocalStore(tmp_path / "lake")
    res = R.retrain(store, now=datetime(2026, 10, 12), upload_batch=True, add_live_week=False)
    assert res["rows"] == 1800
    assert pq.read_table(tmp_path / "lake" / R.TRAINING / "batch.parquet").num_rows == 1800


def test_retrain_adds_the_last_complete_live_week(tmp_path, monkeypatch):
    from datetime import date

    _params(tmp_path, monkeypatch)
    weeks = []

    def live_week(store, monday, tmp):
        weeks.append(monday)
        return pa.Table.from_pylist(_rows(n=100, seed=2))

    monkeypatch.setattr(R, "live_week", live_week)
    store = LocalStore(tmp_path / "lake")
    batch = tmp_path / "batch.parquet"
    pq.write_table(pa.Table.from_pylist(_rows()), batch)
    store.commit({f"{R.TRAINING}/batch.parquet": batch}, Manifest(), "seed: the batch training table")
    res = R.retrain(store, now=datetime(2026, 10, 23))           # labels complete up to Tue 20 Oct
    assert weeks == [date(2026, 10, 12)] and res["rows"] == 1800 + 300
    assert (tmp_path / "lake" / R.TRAINING / "live-2026-10-12.parquet").exists()
