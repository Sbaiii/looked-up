from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from lookedup.evaluation.metrics import to_jsonable


def test_json_fallback_for_dates_and_durations():
    doc = {"d": date(2026, 8, 17), "t": datetime(2026, 8, 17, 2), "lag": timedelta(hours=2)}
    assert json.loads(json.dumps(doc, default=to_jsonable)) == {"d": "2026-08-17", "t": "2026-08-17T02:00:00", "lag": 7200.0}
    with pytest.raises(TypeError):
        to_jsonable(object())


def _ctx(monkeypatch):
    import duckdb

    from lookedup.analytics.config import load
    from lookedup.evaluation.metrics import Context

    monkeypatch.delenv("LOOKEDUP_PERIOD_END", raising=False)
    con = duckdb.connect()
    con.execute("""CREATE TABLE majors AS SELECT * FROM (VALUES
        (DATE '2026-08-10', 1, ['Sports']), (DATE '2026-08-10', 2, ['Sports']),
        (DATE '2026-08-10', 3, ['Armed conflicts and attacks']), (DATE '2026-08-10', 4, ['Armed conflicts and attacks'])
        ) t(date, qid, sections)""")
    con.execute("""CREATE TABLE ev AS SELECT * FROM (VALUES
        (1, TIMESTAMP '2026-08-09 18:00', 'en', 'sports', 1.0),        -- 6 h before the day: inside
        (2, TIMESTAMP '2026-08-11 05:00', 'es', 'sports', 0.0),        -- 29 h after the day starts: inside
        (3, TIMESTAMP '2026-08-11 06:00', 'en', 'death', 3.0),         -- exactly day + 24 h + 6 h: the bound is exclusive
        (9, TIMESTAMP '2026-07-01 00:00', 'en', 'death', 2.0)          -- before the evaluation period
        ) t(qid, start_hour, lead_lang, category, median_spread_lag_hours)""")
    con.execute("ALTER TABLE ev ALTER median_spread_lag_hours TYPE DOUBLE")   # as in the warehouse (median is DOUBLE)
    con.execute("CREATE TABLE portal_qids AS SELECT * FROM (VALUES (DATE '2026-08-12', 2), (DATE '2026-08-20', 3)) t(date, qid)")
    return Context(con, load())


def test_recall_window(monkeypatch):
    from lookedup.evaluation.metrics import recall

    ctx = _ctx(monkeypatch)
    assert recall(ctx, "ev", 6) == {"pairs": 4, "detected": 2, "recall": 0.5}
    assert recall(ctx, "ev", 7)["detected"] == 3


def test_recall_by_section(monkeypatch):
    from lookedup.evaluation.metrics import recall_by_section

    rows = {r[0]: r[1:] for r in recall_by_section(_ctx(monkeypatch), "ev", 6)}
    assert rows["Sports"] == (2, 2, 1.0) and rows["Armed conflicts and attacks"] == (2, 0, 0.0)


def test_precision_proxy(monkeypatch):
    from lookedup.evaluation.metrics import precision_proxy

    res = precision_proxy(_ctx(monkeypatch), "ev")
    assert res == {"events": 3, "in_portal": 1, "precision_proxy": 1 / 3}      # QID 9 is outside the period


def test_counts_keep_to_the_period(monkeypatch):
    from lookedup.evaluation.metrics import event_count, lead_counts

    ctx = _ctx(monkeypatch)
    assert event_count(ctx, "ev") == 3
    assert lead_counts(ctx, "ev") == [("en", 2), ("es", 1)]


def test_h4_needs_enough_events(monkeypatch):
    from lookedup.evaluation.metrics import h4_spread

    res = h4_spread(_ctx(monkeypatch), "ev")
    assert res["n_a"] == 1 and res["n_b"] == 2 and res["verdict"].startswith("inconclusive")


def test_h4_rejected_in_the_reverse_direction(monkeypatch):
    from lookedup.evaluation.metrics import h4_spread

    ctx = _ctx(monkeypatch)
    ctx.con.execute("DELETE FROM ev")
    rows = [(i, "death", 2.5) for i in range(12)] + [(100 + i, "sports", 1.0) for i in range(12)]
    ctx.con.executemany("INSERT INTO ev VALUES (?, TIMESTAMP '2026-08-10 12:00', 'en', ?, ?)", rows)
    res = h4_spread(ctx, "ev")
    assert res["median_a"] == 2.5 and res["median_b"] == 1.0 and res["verdict"] == "rejected"


def test_matched_events(monkeypatch):
    from lookedup.evaluation.metrics import matched_events

    ctx = _ctx(monkeypatch)
    assert matched_events(ctx, "ev") == "matched"
    got = sorted(ctx.con.execute("SELECT qid, portal_date FROM matched").fetchall())
    assert [q for q, _ in got] == [1, 2, 3]                               # QID 3 is inside 24 h, though not inside 6 h


def test_detection_delays(monkeypatch):
    from datetime import datetime

    import lookedup.evaluation.timestamps as T
    from lookedup.evaluation.metrics import detection_delays

    ctx = _ctx(monkeypatch)
    ctx.con.execute("ALTER TABLE majors ADD COLUMN title VARCHAR")
    ctx.con.execute("UPDATE majors SET title = 'Article ' || qid")
    times = {"Article 1": datetime(2026, 8, 9, 15, 40), "Article 2": None, "Article 3": datetime(2026, 8, 11, 7, 0)}
    monkeypatch.setattr(T, "event_time", lambda title, d: times[title] and {"time": times[title], "source": "infobox_timestamp"})
    res = detection_delays(ctx, "ev")
    assert res["n"] == 2
    assert sorted(d["delay_hours"] for d in res["rows"]) == [-1.0, 3.0]


def _warehouse(tmp_path):
    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq

    w = tmp_path / "w.duckdb"
    con = duckdb.connect(str(w))
    con.execute("""CREATE TABLE int_spikes AS SELECT * FROM (VALUES
        (1, 'en', TIMESTAMP '2026-08-10 10:00', 20.0, false, false),
        (1, 'fr', TIMESTAMP '2026-08-10 11:00', 15.0, false, false),
        (1, 'de', TIMESTAMP '2026-08-10 12:00', 9.0, false, false),
        (1, 'ja', TIMESTAMP '2026-08-10 13:00', 50.0, true, false)) t(qid, lang, ts_hour_start, surprise, is_automated, is_low_mobile)""")
    con.execute("ALTER TABLE int_spikes ADD COLUMN views BIGINT DEFAULT 1000")
    con.execute("ALTER TABLE int_spikes ADD COLUMN baseline_median DOUBLE DEFAULT 100")
    con.close()
    gt = tmp_path / "gt.parquet"
    pq.write_table(pa.table({"date": [datetime(2026, 8, 10).date()] * 3, "qid": [1, 1, 2], "section": ["Sports", "Sports", "Law"],
                             "link_title": ["X", "X", "Y"], "is_major": [True, True, False], "depth": [1, 2, 1]}), gt)
    return w, gt


def test_open_context(tmp_path, monkeypatch):
    from lookedup.analytics.config import load
    from lookedup.evaluation.metrics import open_context

    monkeypatch.delenv("LOOKEDUP_PERIOD_END", raising=False)
    ctx = open_context(*_warehouse(tmp_path), load())
    assert ctx.con.sql("SELECT count(*) FROM spikes_ok").fetchone()[0] == 3
    assert ctx.con.sql("SELECT count(*) FROM spikes_s1").fetchone()[0] == 4
    assert ctx.con.sql("SELECT qid, sections FROM majors").fetchall() == [(1, ["Sports"])]
    assert ctx.con.sql("SELECT count(*) FROM portal_qids").fetchone()[0] == 2


def test_ablation_grid(tmp_path, monkeypatch):
    from lookedup.analytics.config import load
    from lookedup.evaluation.metrics import ablation_grid, open_context

    monkeypatch.delenv("LOOKEDUP_PERIOD_END", raising=False)
    grid = ablation_grid(open_context(*_warehouse(tmp_path), load()))
    assert len(grid) == 27
    assert sum(g["primary"] for g in grid) == 1 and sum(g["winner"] for g in grid) == 1
    two = [g for g in grid if g["min_languages"] == 2 and g["r3_threshold"] == 6]
    assert all(g["events"] == 1 and g["recall_24h"] == 1.0 for g in two)        # en and fr spike within the window
    assert all(g["events"] == 0 for g in grid if g["min_languages"] == 5)


def test_h2_lead_language(monkeypatch, tmp_path):
    import json

    import pyarrow as pa

    import lookedup.analytics.entities as E
    from lookedup.evaluation.metrics import h2_lead_language

    ctx = _ctx(monkeypatch)
    ctx.con.execute("ALTER TABLE ev ADD COLUMN event_id VARCHAR")
    ctx.con.execute("UPDATE ev SET event_id = 'E' || qid")
    ctx.con.execute("ATTACH ':memory:' AS wh")
    ctx.con.execute("""CREATE TABLE wh.main.dim_entities AS SELECT * FROM (VALUES
        (1, [30], []), (2, [], [90]), (3, [142], [])) t(qid, countries, locations)""")
    claims = {30: {"P37": [1860]}, 142: {"P37": [150]}, 90: {"P17": [29]}, 29: {"P37": [1321]}}
    monkeypatch.setattr(E, "fetch_claims", lambda qids, cache: pa.table({
        "qid": sorted(qids), "label_en": [None] * len(qids), "claims_json": [json.dumps(claims[q]) for q in sorted(qids)]}))
    res = h2_lead_language(ctx, "ev", tmp_path / "claims.parquet")
    # QID 1: led by en in an English-speaking country (hit); QID 2: led by es, located in a Spanish-speaking
    # country through its location (hit); QID 3: led by en in a French-speaking country (miss)
    assert res["geolocatable"] == 3 and res["lead_is_official"] == 2 and res["verdict"] == "supported"
    assert res["geolocatable_non_english_countries"] == 2 and res["share_non_english_countries"] == 0.5


def test_detection_delays_without_timestamps(monkeypatch):
    import lookedup.evaluation.timestamps as T
    from lookedup.evaluation.metrics import detection_delays

    ctx = _ctx(monkeypatch)
    ctx.con.execute("ALTER TABLE majors ADD COLUMN title VARCHAR")
    monkeypatch.setattr(T, "event_time", lambda title, d: None)
    assert detection_delays(ctx, "ev") == {"n": 0, "rows": []}


def test_detection_delay_shares(monkeypatch):
    from datetime import datetime

    import lookedup.evaluation.timestamps as T
    from lookedup.evaluation.metrics import detection_delays

    ctx = _ctx(monkeypatch)
    ctx.con.execute("ALTER TABLE majors ADD COLUMN title VARCHAR")
    ctx.con.execute("UPDATE majors SET title = 'Article ' || qid")
    times = {"Article 1": datetime(2026, 8, 9, 15, 40), "Article 2": datetime(2026, 8, 1, 0, 0), "Article 3": datetime(2026, 8, 11, 7, 0)}
    monkeypatch.setattr(T, "event_time", lambda title, d: {"time": times[title], "source": "infobox_timestamp"})
    res = detection_delays(ctx, "ev")
    vals = sorted(d["delay_hours"] for d in res["rows"])
    assert res["n"] == 3 and res["median"] == vals[1] and res["p25"] == vals[0]
    assert res["share_negative"] == sum(v < 0 for v in vals) / 3 and res["share_le_6h"] == sum(0 <= v <= 6 for v in vals) / 3


def test_h2_skips_events_without_a_tracked_official_language(monkeypatch, tmp_path):
    import json

    import pyarrow as pa

    import lookedup.analytics.entities as E
    from lookedup.evaluation.metrics import h2_lead_language

    ctx = _ctx(monkeypatch)
    ctx.con.execute("ALTER TABLE ev ADD COLUMN event_id VARCHAR")
    ctx.con.execute("UPDATE ev SET event_id = 'E' || qid")
    ctx.con.execute("ATTACH ':memory:' AS wh")
    ctx.con.execute("""CREATE TABLE wh.main.dim_entities AS SELECT * FROM (VALUES
        (1, [30], []), (2, [77], []), (3, [], [])) t(qid, countries, locations)""")
    claims = {30: {"P37": [1860]}, 77: {"P37": [999999]}}               # 77: a language outside our set
    monkeypatch.setattr(E, "fetch_claims", lambda qids, cache: pa.table({
        "qid": sorted(qids), "label_en": [None] * len(qids), "claims_json": [json.dumps(claims[q]) for q in sorted(qids)]}))
    res = h2_lead_language(ctx, "ev", tmp_path / "claims.parquet")
    assert res["geolocatable"] == 1 and res["lead_is_official"] == 1          # only QID 1 can be placed
