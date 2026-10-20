from __future__ import annotations

import json
from datetime import datetime

import pyarrow.parquet as pq
from conftest import HOURLY_SAMPLE, LANGS

from lookedup.compact import compact_local
from lookedup.store import day_path
from lookedup.transform import hourly_dump_to_table


def test_compact_migrates_hour_files_to_a_day_file(tmp_path, article_filter):
    root = tmp_path / "lake"
    hours = [datetime(2026, 9, 13, 14), datetime(2026, 9, 13, 15)]
    manifest = {"schema_version": 1, "hours": {}}
    for ts in hours:  # the Phase 1 layout: one file per hour
        t = hourly_dump_to_table(HOURLY_SAMPLE, ts, LANGS, article_filter)
        rel = f"data/hourly/year=2026/month=09/day=13/hour={ts:%H}.parquet"
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(t, root / rel)
        manifest["hours"][f"{ts:%Y-%m-%dT%H}:00:00Z"] = {"path": rel, "rows": t.num_rows, "bytes": 1,
                                                          "source": "hourly_dump", "ingested_at": "x"}
    (root / "data" / "manifest.json").write_text(json.dumps(manifest))

    [rep] = compact_local(root)
    assert rep["hours"] == 2 and rep["bytes_day_file"] > 0
    assert not (root / "data/hourly/year=2026/month=09/day=13").exists()
    day = pq.read_table(root / day_path(hours[0]))
    assert day.num_rows == rep["rows"]
    keys = list(zip(day["lang"].to_pylist(), day["title"].to_pylist(), day["ts_hour_start"].to_pylist(), strict=True))
    assert keys == sorted(keys)
    m = json.loads((root / "data" / "manifest.json").read_text())
    assert m["schema_version"] == 2 and m["hour_count"] == 2
    assert {e["path"] for e in m["hours"].values()} == {day_path(hours[0])}
    assert all("bytes" not in e for e in m["hours"].values())
    assert m["files"][day_path(hours[0])]["rows"] == day.num_rows


def test_compact_skips_days_without_hour_files(tmp_path):
    from lookedup.compact import compact_local

    (tmp_path / "data" / "hourly" / "year=2026" / "month=09" / "day=13").mkdir(parents=True)
    assert compact_local(tmp_path) == []


def test_compact_skips_stray_files(tmp_path):
    from lookedup.compact import compact_local

    month = tmp_path / "data" / "hourly" / "year=2026" / "month=09"
    month.mkdir(parents=True)
    (month / "day=13").write_text("not a folder")
    assert compact_local(tmp_path) == []


def test_compact_leaves_other_days_alone(tmp_path, article_filter):
    root = tmp_path / "lake"
    ts = datetime(2026, 9, 13, 14)
    t = hourly_dump_to_table(HOURLY_SAMPLE, ts, LANGS, article_filter)
    rel = "data/hourly/year=2026/month=09/day=13/hour=14.parquet"
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(t, root / rel)
    other = {"path": "data/hourly/year=2026/month=09/day=12.parquet", "rows": 5, "bytes": 9, "source": "hourly_dump",
             "ingested_at": "x"}
    manifest = {"schema_version": 1, "hours": {
        "2026-09-13T14:00:00Z": {"path": rel, "rows": t.num_rows, "bytes": 1, "source": "hourly_dump", "ingested_at": "x"},
        "2026-09-12T10:00:00Z": dict(other)}}
    (root / "data" / "manifest.json").write_text(json.dumps(manifest))
    compact_local(root)
    m = json.loads((root / "data" / "manifest.json").read_text())
    assert m["hours"]["2026-09-12T10:00:00Z"]["path"] == other["path"] and m["hours"]["2026-09-12T10:00:00Z"]["bytes"] == 9
    assert m["hours"]["2026-09-13T14:00:00Z"]["path"] == day_path(ts)
