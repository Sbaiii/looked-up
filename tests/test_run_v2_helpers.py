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


def test_variant_built_once(tmp_path, monkeypatch):
    ev = _events(tmp_path, monkeypatch)
    name = ev.variant(2)
    assert name == "ev_n2" and ev.variant(2) == name
    assert ev.con.sql(f"SELECT count(*) FROM {name}").fetchone()[0] == 1          # en and fr within the window
    assert ev.con.sql(f"SELECT count(*) FROM {ev.variant(3)}").fetchone()[0] == 0


def test_cached_builds_once_then_reads(tmp_path, monkeypatch):
    from datetime import date

    monkeypatch.setattr(R, "CACHE", tmp_path / "eval")
    calls = []

    def build():
        calls.append(1)
        return [{"qid": 1, "day": date(2026, 8, 1), "name": "Zoë"}]

    assert R._cached("deaths", build, refresh=False) == [{"qid": 1, "day": "2026-08-01", "name": "Zoë"}]
    assert R._cached("deaths", build, refresh=False)[0]["day"] == "2026-08-01"
    assert len(calls) == 1 and "Zoë" in (tmp_path / "eval" / "gt2b_deaths.json").read_text(encoding="utf-8")


def test_cached_refresh_rebuilds(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "CACHE", tmp_path)
    R._cached("quakes", lambda: [{"n": 1}], refresh=False)
    assert R._cached("quakes", lambda: [{"n": 2}], refresh=False) == [{"n": 1}]
    assert R._cached("quakes", lambda: [{"n": 2}], refresh=True) == [{"n": 2}]
    assert R._cached("quakes", lambda: [{"n": 3}], refresh=False) == [{"n": 2}]


def test_write_skips_empty_and_writes_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "OUT", tmp_path)
    R._write("none.csv", [])
    R._write("rows.csv", [{"qid": 1, "detected": True}, {"qid": 2, "detected": False}])
    assert not (tmp_path / "none.csv").exists()
    assert (tmp_path / "rows.csv").read_text(encoding="utf-8") == "qid,detected\n1,True\n2,False\n"


def test_delay_quartiles_by_nearest_rank():
    d = R._dist([5.0, 1.0, 3.0, 2.0, 4.0])
    assert (d["p25"], d["median"], d["p75"]) == (2.0, 3.0, 4.0)
    assert R._dist([7.0]) == {"n": 1, "median": 7.0, "p25": 7.0, "p75": 7.0, "min": 7.0, "max": 7.0, "share_le_4h": 0.0}


def test_claims_by_qid():
    import pyarrow as pa

    t = pa.table({"qid": [1, 2], "claims_json": ['{"P31": [5]}', '{"P17": [30]}']})
    assert R._claims(t) == {1: {"P31": [5]}, 2: {"P17": [30]}}
    assert R._claims(pa.table({"qid": pa.array([], pa.int64()), "claims_json": pa.array([], pa.string())})) == {}


def test_country_from_article_then_us_state():
    base = {"article_countries": [], "region_is_us_state": False, "place_qids": []}
    assert R._country(base | {"article_countries": [17, 30]}, {}) == 17
    assert R._country(base | {"region_is_us_state": True, "place_qids": [99]}, {}) == 30
    assert R._country(base, {}) is None
