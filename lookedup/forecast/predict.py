"""Live forecasts for open events (Phase 4 Step 3): every event that started less than 24 h ago is scored with
the model for the largest snapshot offset its age allows (t0, t0 + 1 h, t0 + 3 h; t0 = detection hour).

Models come from the lake (data/models/models.json + LightGBM text files, see lookedup.forecast.retrain).
Probabilities are only produced for tiers not reached yet.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from lookedup.forecast import train as T
from lookedup.forecast.features import FADE_CAP, snapshot_sql

log = logging.getLogger(__name__)

MODELS_PREFIX = "data/models"
MANIFEST = f"{MODELS_PREFIX}/models.json"


def load_models(store, tmp: Path) -> tuple[dict, dict]:
    """(manifest, {key: (booster, encoder, platt)}); empty when no models are published yet."""
    m = store.fetch(MANIFEST, tmp)
    if not m:
        return {}, {}
    manifest = json.loads(m.read_text())
    models = {}
    for key, spec in manifest["models"].items():
        f = store.fetch(f"{MODELS_PREFIX}/{spec['file']}", tmp)
        if f:
            models[key] = (T.load(f), T.Encoder.from_json(spec["encoder"]), tuple(spec["platt"]) if spec.get("platt") else None)
    return manifest, models


def live_relations(con, events: list[dict], categories: dict[int, str], entity_classes: dict[int, str],
                   titles: dict[int, dict[str, str]], hourly_files: list[Path], spikes_view: str = "_sp") -> None:
    """Temp relations _fev, _fdims, _fviews for snapshot_sql from the live inputs (spikes view from events_from_spikes)."""
    con.execute("CREATE OR REPLACE TEMP TABLE _fev(event_id VARCHAR, qid BIGINT, start_hour TIMESTAMP, lead_lang VARCHAR, "
                "breadth INT, event_class VARCHAR, category VARCHAR)")
    con.executemany("INSERT INTO _fev VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(e["event_id"], e["qid"], e["start_hour"], e["lead_lang"], e["breadth"], e["event_class"],
                      categories.get(e["qid"], "other")) for e in events])
    con.execute("CREATE OR REPLACE TEMP TABLE _fdims(qid BIGINT, entity_class VARCHAR, n_languages INT)")
    con.executemany("INSERT INTO _fdims VALUES (?, ?, ?)",
                    [(q, entity_classes.get(q, "other"), len(titles.get(q, {}))) for q in {e["qid"] for e in events}])
    paths = ", ".join(f"'{p}'" for p in hourly_files) or "''"
    # article-hours with >= 100 views; baseline from candidate rows where present (targets only, retraining)
    con.execute(f"""CREATE OR REPLACE TEMP VIEW _fviews AS
        SELECT h.lang, h.title, h.ts_hour_start, h.views_desktop + h.views_mobile AS views,
               coalesce(s.baseline_median, h.views_desktop + h.views_mobile) AS baseline_median
        FROM read_parquet([{paths}]) h
        LEFT JOIN (SELECT DISTINCT lang, title, ts_hour_start, baseline_median FROM {spikes_view}) s
          USING (lang, title, ts_hour_start)
        WHERE h.views_desktop + h.views_mobile >= 100""")


def entity_classes(qids) -> dict[int, str]:
    from lookedup.analytics.config import load
    from lookedup.analytics.entities import classify, fetch_claims
    from lookedup.settings import DATA_DIR

    if not qids:
        return {}
    cfg = load()
    claims = fetch_claims(qids, DATA_DIR / "warehouse" / "entity_claims.parquet")
    return {q: classify(json.loads(c), cfg) for q, c in zip(claims["qid"].to_pylist(), claims["claims_json"].to_pylist())}


def snapshots(con, targets: bool = False, data_end: str | None = None) -> list[dict]:
    rel = con.sql(snapshot_sql("_fev", "_sp", "_fviews", "_fdims", targets=targets, data_end=data_end))
    cols = rel.columns
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def forecast_open(con, events: list[dict], now: datetime, last_hour: datetime, manifest: dict, models: dict) -> dict[str, dict]:
    """event_id -> forecast for events that started in the last 24 h (relations from live_relations must exist)."""
    if not models:
        return {}
    open_ids = {e["event_id"]: e for e in events
                if e["event_class"] != "single_language" and e["start_hour"] >= now - timedelta(hours=24)}
    best: dict[str, dict] = {}
    for r in snapshots(con):
        if r["event_id"] in open_ids and r["snapshot_ts"] <= last_hour:
            if r["event_id"] not in best or r["offset_h"] > best[r["event_id"]]["offset_h"]:
                best[r["event_id"]] = r
    out: dict[str, dict] = {}
    by_offset: dict[int, list[dict]] = {}
    for r in best.values():
        by_offset.setdefault(r["offset_h"], []).append(r)
    for off, rows in by_offset.items():
        res = {r["event_id"]: {"offset_h": off, "model_version": manifest.get("version")} for r in rows}
        for target, (_, threshold) in T.TARGETS.items():
            key = f"{target}_t{off}"
            if key not in models:
                continue
            booster, enc, ab = models[key]
            todo = [r for r in rows if open_ids[r["event_id"]]["breadth"] < threshold]   # never for a reached tier
            if todo:
                p = T.calibrate(T.score(booster, enc.matrix(todo)), ab) if ab else T.score(booster, enc.matrix(todo))
                for r, v in zip(todo, p):
                    res[r["event_id"]][f"p_{target}"] = round(float(v), 3)
        if off == 3:
            for target in T.M2_TARGETS:
                key = f"m2_{target}"
                if key in models:
                    booster, enc, _ = models[key]
                    pred = np.expm1(T.score(booster, enc.matrix(rows)))
                    for r, v in zip(rows, pred):
                        if target == "excess_next24":
                            res[r["event_id"]]["predicted_excess_24h"] = int(max(v, 0))
                        else:
                            h = float(min(max(v, 0), FADE_CAP))
                            res[r["event_id"]]["fade_eta_hours"] = round(h, 1)
                            res[r["event_id"]]["fade_eta"] = f"{r['snapshot_ts'] + timedelta(hours=round(h)):%Y-%m-%dT%H}:00Z"
        out |= res
    return out
