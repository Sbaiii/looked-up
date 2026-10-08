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
    keys = list(zip(day["lang"].to_pylist(), day["title"].to_pylist(), day["ts_hour_start"].to_pylist()))
    assert keys == sorted(keys)
    m = json.loads((root / "data" / "manifest.json").read_text())
    assert m["schema_version"] == 2 and m["hour_count"] == 2
    assert {e["path"] for e in m["hours"].values()} == {day_path(hours[0])}
    assert all("bytes" not in e for e in m["hours"].values())
    assert m["files"][day_path(hours[0])]["rows"] == day.num_rows
