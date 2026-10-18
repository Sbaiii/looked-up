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


def test_run_by_day_with_nothing_to_do(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "STAGING", tmp_path)
    rel = batch.run_by_day(duckdb.connect(), [], lambda d: f"SELECT DATE '{d}' AS day, 1 AS n", "empty")
    assert rel.columns == ["day", "n"] and rel.fetchall() == []


def test_prepare_event_inputs():
    con = duckdb.connect()
    spikes = con.sql("""SELECT * FROM (VALUES ('en', 'A', 1, false), ('en', 'B', 2, true), ('fr', 'C', NULL, false))
                        t(lang, title, qid, is_automated)""")
    baselines = con.sql("""SELECT * FROM (VALUES (TIMESTAMP '2026-08-10 10:00', 'en', 'A', 500, 50.0),
                           (TIMESTAMP '2026-08-10 10:00', 'en', 'B', 900, 90.0)) t(ts_hour_start, lang, title, views, baseline_median)""")
    ok, scored = batch.prepare_event_inputs(con, spikes, baselines, "t")
    assert (ok, scored) == ("_ok_t", "_scored_t")
    assert sorted(r[1] for r in con.sql(f"SELECT * FROM {ok}").fetchall()) == ["A", "C"]
    assert con.sql(f"SELECT lang, views, qid FROM {scored}").fetchall() == [("en", 500, 1)]
