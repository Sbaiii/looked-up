"""Small helpers of the Phase 2b runner (no warehouse needed)."""
from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from lookedup import db
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
    assert db.one(ev.con, f"SELECT count(*) FROM {name}")[0] == 1          # en and fr within the window
    assert db.one(ev.con, f"SELECT count(*) FROM {ev.variant(3)}")[0] == 0


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


def test_country_from_places_region_first():
    base = {"article_countries": [], "region_is_us_state": False}
    claims = {10: {"P31": [515], "P17": [17]}, 20: {"P31": [6256]}, 30: {"P31": [107425], "P17": [148]}}
    assert R._country(base | {"place_qids": [10, 20]}, claims) == 20          # the region (last) is a country itself
    assert R._country(base | {"place_qids": [20, 30]}, claims) == 148         # the region's own country wins
    assert R._country(base | {"place_qids": [10, 99]}, claims) == 17          # unknown region, then the locality's P17
    assert R._country(base | {"place_qids": [99]}, claims) is None


class _FakeEvents:
    """Events answered from a {qid: (start_hour, lead_lang, breadth)} table, the same for every variant."""
    hits: ClassVar[dict] = {}

    def __init__(self, cfg):
        import duckdb

        self.con = duckdb.connect()
        self.con.execute("ATTACH ':memory:' AS wh")
        self.con.execute("CREATE TABLE wh.main.stg_sitelinks AS SELECT * FROM (VALUES (1, 'en'), (1, 'fr')) t(qid, lang)")
        self.tables = {"primary": "primary"}

    def variant(self, n):
        return f"ev_n{n}"

    def first(self, table, qids, lo, hi):
        found = [(s, q) for q in qids if q in self.hits for s in [self.hits[q][0]] if lo <= s <= hi]
        if not found:
            return None
        s, q = min(found)
        return {"qid": q, "start_hour": s, "lead_lang": self.hits[q][1], "breadth": self.hits[q][2],
                "event_class": "multi_language"}


def _phase2b(tmp_path, monkeypatch):
    import json

    import pyarrow as pa

    cache = tmp_path / "eval"
    cache.mkdir()
    gts = {
        "deaths": [{"date": "2026-08-01", "title": "Seen", "qid": 1, "n_languages": 12, "announcement": "2026-08-01T09:30:00"},
                   {"date": "2026-08-02", "title": "Missed", "qid": 2, "n_languages": 6, "announcement": None},
                   {"date": "2026-07-01", "title": "Too early", "qid": 3, "n_languages": 30, "announcement": None}],
        "quakes": [{"usgs_id": "u1", "origin": "2026-08-10T12:20:00", "mag": 7.1, "place": "near X, Japan", "article_qid": 10,
                    "article_countries": [17], "place_qids": [], "region_is_us_state": False},
                   {"usgs_id": "u2", "origin": "2026-08-20T03:00:00", "mag": 6.2, "place": "Y", "article_qid": None,
                    "article_countries": [], "place_qids": [], "region_is_us_state": False}],
        "matches": [{"kickoff": "2026-07-18T21:00:00", "teams": ["France", "England"], "team_qids": [20, 21], "match_qid": None},
                    {"kickoff": "2026-07-18T21:00:00", "teams": ["France", "England"], "team_qids": [20, 21], "match_qid": None},
                    {"kickoff": None, "teams": ["A", "B"], "team_qids": [], "match_qid": None},
                    {"kickoff": "2026-07-10T19:00:00", "teams": ["C", "D"], "team_qids": [22], "match_qid": None}]}
    for name, rows in gts.items():
        (cache / f"gt2b_{name}.json").write_text(json.dumps(rows))
    _FakeEvents.hits = {1: (datetime(2026, 8, 1, 11), "en", 9), 10: (datetime(2026, 8, 10, 14), "ja", 7),
                        20: (datetime(2026, 7, 18, 20), "fr", 21)}
    claims = {17: {"P37": [5287]}}
    monkeypatch.setattr(R, "CACHE", cache)
    monkeypatch.setattr(R, "OUT", tmp_path)
    monkeypatch.setattr(R, "Events", _FakeEvents)
    monkeypatch.setattr(R, "active_codes", lambda: ["en", "fr", "ja"])
    monkeypatch.setattr(R, "fetch_claims", lambda qids, cache: pa.table({
        "qid": sorted(qids), "claims_json": [json.dumps(claims.get(q, {})) for q in sorted(qids)]}))
    return R.evaluate()


def test_phase2b_evaluation_end_to_end(tmp_path, monkeypatch):
    res = _phase2b(tmp_path, monkeypatch)
    g1, g2, g3 = res["gt1"], res["gt2"], res["gt3"]
    assert (g1["entries_total"], g1["out_of_window"], g1["n"], g1["detected"]) == (3, 1, 2, 1)
    assert g1["verdict_h1b_1"] == "rejected" and g1["delay_from_announcement"]["median"] == 2.0   # 09:30 -> 11:00, floored to 09:00
    assert g2["m65_plus"] == {"n": 1, "detected": 1, "recall": 1.0} and g2["m60_65"]["detected"] == 0
    assert g2["h2b"] == {"qualifying": 1, "lead_is_country_language": 1, "share": 1.0}
    assert g2["verdict_h5"] == "inconclusive (< 5 detected)" and g2["verdict_h2b"] == "inconclusive (< 5 qualifying)"
    assert g3["n"] == 1 and g3["detected"] == 1 and g3["excluded"] == 2                # the duplicate counts once
    assert g3["excluded_reasons"] == {"no Wikipedia kick-off time": 1, "out of the scored period": 1}
    assert (tmp_path / "phase2b_metrics.json").exists() and (tmp_path / "phase2b_gt3_excluded.csv").exists()


def test_phase2b_death_breakdowns(tmp_path, monkeypatch):
    g1 = _phase2b(tmp_path, monkeypatch)["gt1"]
    assert g1["by_languages"]["10-19"] == {"n": 1, "detected": 1, "recall": 1.0}
    assert g1["by_languages"]["5-9"] == {"n": 1, "detected": 0, "recall": 0.0} and g1["by_languages"][">=20"]["n"] == 0
    assert set(g1["ablation"]) == {"n2", "n3", "n5"} and g1["by_class"] == {"multi_language": 1, "single_language": 0}


def test_phase2b_quake_verdict_and_rows(tmp_path, monkeypatch):
    import csv

    g2 = _phase2b(tmp_path, monkeypatch)["gt2"]
    assert g2["verdict_h1b_2"] == "supported" and g2["with_article"] == 1 and g2["h5_delay"]["n"] == 1
    with open(tmp_path / "phase2b_gt2_earthquakes.csv", encoding="utf-8") as f:
        rows = {r["usgs_id"]: r for r in csv.DictReader(f)}
    assert rows["u1"]["country"] == "17" and rows["u1"]["lead_is_country_language"] == "True" and rows["u1"]["delay_h"] == "2.0"
    assert rows["u2"]["detected"] == "False" and rows["u2"]["lead_is_country_language"] == ""


def test_floor_on_the_hour():
    assert R._floor(datetime(2026, 8, 17, 2)) == datetime(2026, 8, 17, 2)


def test_recall_none_detected():
    assert R._recall([{"detected": False}] * 3) == {"n": 3, "detected": 0, "recall": 0.0}
