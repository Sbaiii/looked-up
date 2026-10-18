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


def test_delay_distribution():
    assert R._dist([]) == {"n": 0}
    d = R._dist([0, 1, 2, 3, 10])
    assert d["n"] == 5 and d["median"] == 2 and d["min"] == 0 and d["max"] == 10
    assert d["share_le_4h"] == 0.8


def _events(tmp_path, monkeypatch):
    import duckdb

    from lookedup.analytics.config import load

    w = tmp_path / "w.duckdb"
    con = duckdb.connect(str(w))
    con.execute("""CREATE TABLE int_spikes AS SELECT * FROM (VALUES
        (1, 'en', TIMESTAMP '2026-08-10 10:00', 20.0, false, 1000, 100.0),
        (1, 'fr', TIMESTAMP '2026-08-10 11:00', 15.0, false, 800, 100.0)) t(qid, lang, ts_hour_start, surprise, is_automated, views, baseline_median)""")
    con.execute("""CREATE TABLE fct_attention_events AS SELECT * FROM (VALUES
        (1, TIMESTAMP '2026-08-10 12:00', 'en', 3, 'multi_language'),
        (1, TIMESTAMP '2026-08-12 09:00', 'de', 4, 'multi_language')) t(qid, start_hour, lead_lang, breadth, event_class)""")
    con.close()
    monkeypatch.setattr(R, "WAREHOUSE_DB", w)
    return R.Events(load())


def test_first_event_in_window(tmp_path, monkeypatch):
    ev = _events(tmp_path, monkeypatch)
    got = ev.first("primary" and ev.tables["primary"], [1, 2], datetime(2026, 8, 10), datetime(2026, 8, 13))
    assert got == {"qid": 1, "start_hour": datetime(2026, 8, 10, 12), "lead_lang": "en", "breadth": 3, "event_class": "multi_language"}
    assert ev.first(ev.tables["primary"], [1], datetime(2026, 8, 11), datetime(2026, 8, 11, 23)) is None
    assert ev.first(ev.tables["primary"], [], datetime(2026, 8, 10), datetime(2026, 8, 13)) is None
