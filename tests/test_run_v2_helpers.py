"""Small helpers of the Phase 2b runner (no warehouse needed)."""
from __future__ import annotations

from datetime import datetime

from lookedup.evaluation import run_v2 as R


def test_recall_counts_detected_rows():
    assert R._recall([]) == {"n": 0, "detected": 0, "recall": None}
    rows = [{"detected": True}, {"detected": False}, {"detected": True}, {"detected": False}]
    assert R._recall(rows) == {"n": 4, "detected": 2, "recall": 0.5}
    assert R._recall([{"hit": 1}], key="hit")["recall"] == 1.0


def test_floor_and_timestamp_helpers():
    assert R._floor(datetime(2026, 8, 17, 2, 57, 13, 5)) == datetime(2026, 8, 17, 2)
    assert R._ts("2026-08-17T02:00:00") == datetime(2026, 8, 17, 2)
    assert R._ts("") is None and R._ts(None) is None
