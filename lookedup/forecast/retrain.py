"""Production models (Phase 4 Step 3): weekly retrain with the backtest's chosen parameters
(config/forecast_params.json) on every labelled snapshot, Platt-calibrated on the most recent 10 days.

Training data on the lake (data/models/training/):
* ``batch.parquet``: the warehouse feature table (16 Jul .. 6 Oct), uploaded once;
* ``live-YYYY-MM-DD.parquet``: one file per week, rebuilt from production spike files and hourly day files
  (excess targets count candidate rows only, ADR 0029), added by the weekly job.

    python -m lookedup.cli forecast-retrain [--upload-batch]
"""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from lookedup import db
from lookedup.forecast import train as T
from lookedup.forecast.predict import MANIFEST, MODELS_PREFIX, live_relations, snapshots
from lookedup.settings import ROOT

log = logging.getLogger(__name__)

PARAMS = ROOT / "config" / "forecast_params.json"
METRICS = ROOT / "docs" / "analysis" / "phase4_metrics.json"
TRAINING = f"{MODELS_PREFIX}/training"
CALIBRATION_DAYS = 10
LABEL_LAG_DAYS = 3          # targets need up to 72 h after the start


def batch_table(con) -> pa.Table:
    from lookedup.warehouse import WAREHOUSE_DB
    con.execute(f"ATTACH '{WAREHOUSE_DB}' AS wh (READ_ONLY)")
    return db.arrow(con.sql("SELECT * FROM wh.main.fct_event_snapshots WHERE start_hour < TIMESTAMP '2026-10-07'"))


def live_week(store, monday: date, tmp: Path) -> pa.Table | None:
    """Snapshots with targets for events starting in [monday, monday + 7 d), from production files."""
    from lookedup.app_export import categories_for, events_from_spikes, titles_from_api
    from lookedup.analytics.config import load
    from lookedup.analytics.entities import classify, fetch_claims
    from lookedup.languages import active_codes
    from lookedup.scorer import spikes_path
    from lookedup.settings import DATA_DIR
    from lookedup.store import day_path

    days = [monday + timedelta(days=i) for i in range(-1, 7 + LABEL_LAG_DAYS + 1)]
    spikes = [f for f in (store.fetch(spikes_path(d), tmp / "s") for d in days) if f]
    hourly = [f for f in (store.fetch(day_path(datetime(d.year, d.month, d.day)), tmp / "h") for d in days) if f]
    if not spikes or not hourly:
        return None
    con = db.connect()
    events, _ = events_from_spikes(con, spikes)
    events = [e for e in events if monday <= e["start_hour"].date() < monday + timedelta(days=7)]
    if not events:
        return None
    cfg = load()
    claims = fetch_claims({e["qid"] for e in events}, DATA_DIR / "warehouse" / "entity_claims.parquet")
    cj = {q: json.loads(c) for q, c in zip(claims["qid"].to_pylist(), claims["claims_json"].to_pylist())}
    classes = {q: classify(c, cfg) for q, c in cj.items()}
    titles = titles_from_api({e["qid"] for e in events}, active_codes())
    live_relations(con, events, categories_for(events), classes, titles, hourly)
    end = con.sql(f"SELECT max(ts_hour_start) FROM read_parquet([{', '.join(repr(str(f)) for f in hourly)}])").fetchone()[0]
    rows = snapshots(con, targets=True, data_end=f"{end:%Y-%m-%d %H:%M:%S}")
    return pa.Table.from_pylist(rows) if rows else None


def train_all(rows: list[dict], params: dict, cutoff: datetime) -> tuple[dict, dict]:
    """Fit every model on rows starting before cutoff - 10 d; Platt on [cutoff - 10 d, cutoff)."""
    cal_lo = cutoff - timedelta(days=CALIBRATION_DAYS)
    fit_rows = [r for r in rows if r["start_hour"] < cal_lo]
    cal_rows = [r for r in rows if cal_lo <= r["start_hour"] < cutoff]
    models, specs = {}, {}
    for target in T.TARGETS:
        for off in T.OFFSETS:
            key = f"{target}_t{off}"
            tr, ca = T.m1_rows(fit_rows, target, off), T.m1_rows(cal_rows, target, off)
            enc = T.Encoder.fit(tr)
            booster = T.fit(enc.matrix(tr), T.labels(tr, target), enc, params[key], "binary")
            ab = T.platt(T.score(booster, enc.matrix(ca)), T.labels(ca, target))
            models[key] = booster
            specs[key] = {"kind": "m1", "target": target, "offset_h": off, "encoder": enc.to_json(), "platt": list(ab)}
    for target in T.M2_TARGETS:
        key = f"m2_{target}"
        tr = T.m2_rows([r for r in rows if r["start_hour"] < cutoff], target)
        enc = T.Encoder.fit(tr)
        models[key] = T.fit(enc.matrix(tr), T.labels(tr, target), enc, params[key], "regression")
        specs[key] = {"kind": "m2", "target": target, "offset_h": 3, "encoder": enc.to_json(), "platt": None}
    return models, specs


def backtest_summary() -> dict:
    """The numbers the app shows (FIG. 05): from the pre-registered backtest."""
    m = json.loads(METRICS.read_text())
    h = m["m1"]["international_t1"]
    return {"auc_international_t1": round(h["model"]["roc_auc"], 3), "pr_auc_international_t1": round(h["model"]["pr_auc"], 3),
            "brier_international_t1": round(h["model"]["brier"], 4),
            "base_rate_international_t1": round(h["model"]["positives"] / h["model"]["n"], 4),
            "lift_top10_international_t1": round(h["model"]["lift_top10"], 2),
            "m2_improvement_over_category_decay": round(m["H8"]["improvement"], 3),
            "calibration_curve": h["calibration_curve"], "test_window": ["2026-09-20", "2026-10-06"]}


def retrain(store, now: datetime | None = None, upload_batch: bool = False, add_live_week: bool = True) -> dict:
    from lookedup.dumps import utcnow
    from lookedup.scorer import _commit

    now = now or utcnow()
    params = json.loads(PARAMS.read_text())
    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        files: dict[str, Path] = {}
        if upload_batch:
            t = batch_table(db.connect())
            pq.write_table(t, tmp / "batch.parquet", compression="zstd")
            files[f"{TRAINING}/batch.parquet"] = tmp / "batch.parquet"
        if add_live_week:
            # the last full week whose targets are complete: Monday .. Sunday ending >= 3 days ago
            last = (now - timedelta(days=LABEL_LAG_DAYS)).date()
            monday = last - timedelta(days=last.weekday() + 7) if last.weekday() < 6 else last - timedelta(days=6)
            if monday >= date(2026, 10, 7):
                week = live_week(store, monday, tmp)
                if week is not None:
                    pq.write_table(week, tmp / f"live-{monday}.parquet", compression="zstd")
                    files[f"{TRAINING}/live-{monday}.parquet"] = tmp / f"live-{monday}.parquet"
        tables = [pq.read_table(f) for k, f in files.items() if k.startswith(TRAINING)]
        for path in sorted(p for p in store.list_prefix(TRAINING) if p.endswith(".parquet") and p not in files):
            f = store.fetch(path, tmp / "t")
            if f:
                tables.append(pq.read_table(f))
        if not tables:
            raise RuntimeError("no training data on the lake (run with --upload-batch once)")
        cols = set.intersection(*(set(t.column_names) for t in tables))
        rows = [r for t in tables for r in t.select(sorted(cols)).to_pylist()]
        cutoff = max(r["start_hour"] for r in rows) + timedelta(hours=1)
        models, specs = train_all(rows, params, cutoff)
        version = f"{now:%Y-%m-%d}"
        out = tmp / "models"
        for key, booster in models.items():
            specs[key]["file"] = f"{version}/{key}.txt"
            specs[key]["bytes"] = T.save(booster, out / version / f"{key}.txt")
            files[f"{MODELS_PREFIX}/{version}/{key}.txt"] = out / version / f"{key}.txt"
        manifest = {"version": version, "trained_at": f"{now:%Y-%m-%dT%H:%M:%SZ}",
                    "training_window": [str(min(r["start_hour"] for r in rows)), str(cutoff)],
                    "calibration_days": CALIBRATION_DAYS, "rows": len(rows), "models": specs,
                    "backtest": backtest_summary()}
        T.write_manifest(out / "models.json", manifest)
        files[MANIFEST] = out / "models.json"
        _commit(store, files, f"data: forecast models {version} ({len(rows)} snapshots)")
    return {"version": version, "rows": len(rows), "bytes": {k: s["bytes"] for k, s in specs.items()}}
