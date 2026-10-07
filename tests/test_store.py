from __future__ import annotations

import json
from datetime import datetime

import pyarrow.parquet as pq

from conftest import HOURLY_SAMPLE, LANGS
from lookedup.store import LocalStore, Manifest, expected_hours, hour_path, missing_hours, write_parquet
from lookedup.transform import SCHEMA, hourly_dump_to_table


def test_hour_path_layout():
    assert hour_path(datetime(2026, 10, 7, 9)) == "data/hourly/year=2026/month=10/day=07/hour=09.parquet"


def test_expected_hours_only_completed_hours():
    now = datetime(2026, 10, 7, 12, 45)
    exp = expected_hours(now, 3)
    # the 12:00 hour is still running, so the last complete hour starts at 11:00
    assert exp == [datetime(2026, 10, 7, 9), datetime(2026, 10, 7, 10), datetime(2026, 10, 7, 11)]
    assert len(expected_hours(now, 72)) == 72


def test_missing_hours_diff():
    m = Manifest()
    m.add(datetime(2026, 10, 7, 10), rows=1, size=1, source="hourly_dump")
    exp = expected_hours(datetime(2026, 10, 7, 12, 45), 3)
    assert missing_hours(m, exp) == [datetime(2026, 10, 7, 9), datetime(2026, 10, 7, 11)]
    for ts in exp:
        m.add(ts, rows=1, size=1, source="pageview_complete")
    assert missing_hours(m, exp) == []


def test_manifest_roundtrip_and_merge():
    m = Manifest()
    m.add(datetime(2026, 10, 7, 9), rows=10, size=100, source="hourly_dump",
          ingested_at=datetime(2026, 10, 7, 12, 50))
    doc = json.loads(m.to_json())
    assert doc["hour_count"] == 1
    assert doc["hours"]["2026-10-07T09:00:00Z"] == {
        "path": "data/hourly/year=2026/month=10/day=07/hour=09.parquet", "rows": 10, "bytes": 100,
        "source": "hourly_dump", "ingested_at": "2026-10-07T12:50:00Z"}
    m2 = Manifest.from_json(m.to_json())
    other = Manifest()
    other.add(datetime(2026, 10, 7, 10), rows=5, size=50, source="pageview_complete")
    m2.merge(other.hours)
    assert m2.present() == {datetime(2026, 10, 7, 9), datetime(2026, 10, 7, 10)}


def test_manifest_rejects_unknown_source():
    import pytest

    with pytest.raises(ValueError):
        Manifest().add(datetime(2026, 1, 1), rows=0, size=0, source="api")


def test_local_store_commit_is_idempotent(tmp_path, article_filter):
    ts = datetime(2026, 9, 13, 14)
    table = hourly_dump_to_table(HOURLY_SAMPLE, ts, LANGS, article_filter)
    f = tmp_path / "staging.parquet"
    size = write_parquet(table, f)
    store = LocalStore(tmp_path / "lake")
    m = Manifest()
    m.add(ts, rows=table.num_rows, size=size, source="hourly_dump")
    for _ in range(2):  # committing the same hour twice never duplicates it
        store.commit({hour_path(ts): f}, m.hours, "test")
    manifest = store.read_manifest()
    assert manifest.present() == {ts}
    back = pq.read_table(tmp_path / "lake" / hour_path(ts))
    assert back.schema.remove_metadata() == SCHEMA
    assert back.num_rows == table.num_rows
