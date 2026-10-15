"""Per-day batching for the incremental dbt python models."""
from __future__ import annotations

from datetime import date

import duckdb

from lookedup.analytics import batch


def test_pending_days():
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT DATE '2026-08-17' AS day UNION ALL SELECT DATE '2026-08-19'")
    start, end = date(2026, 8, 16), date(2026, 8, 20)
    assert batch.pending_days(con, "t", False, start, end) == batch.days_between(start, end)
    assert batch.pending_days(con, "t", True, start, end) == [date(2026, 8, 16), date(2026, 8, 18), date(2026, 8, 20)]


def test_run_by_day(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "STAGING", tmp_path)
    con = duckdb.connect()
    sql = lambda d: f"SELECT DATE '{d}' AS day, {d.day} AS n"
    rel = batch.run_by_day(con, [date(2026, 8, 17), date(2026, 8, 18)], sql, "demo")
    assert sorted(rel.fetchall()) == [(date(2026, 8, 17), 17), (date(2026, 8, 18), 18)]
    assert sorted(p.name for p in (tmp_path / "demo").iterdir()) == ["day=2026-08-17.parquet", "day=2026-08-18.parquet"]
