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
from lookedup.store import LocalStore

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
