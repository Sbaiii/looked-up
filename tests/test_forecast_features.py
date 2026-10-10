from __future__ import annotations

from datetime import datetime, timedelta

import duckdb

from lookedup.forecast.features import snapshot_sql

T0 = datetime(2026, 8, 10, 12)


def _con(spike_rows, view_rows, breadth=3):
    con = duckdb.connect()
    con.execute("CREATE TABLE events(event_id VARCHAR, qid BIGINT, start_hour TIMESTAMP, lead_lang VARCHAR, breadth INT, "
                "event_class VARCHAR, category VARCHAR)")
    con.execute("INSERT INTO events VALUES ('E', 1, ?, 'es', ?, 'multi_language', 'death')", [T0, breadth])
    con.execute("CREATE TABLE spikes(qid BIGINT, lang VARCHAR, title VARCHAR, ts_hour_start TIMESTAMP, surprise DOUBLE, "
                "views INT, baseline_median DOUBLE)")
    con.executemany("INSERT INTO spikes VALUES (1, ?, ?, ?, ?, ?, ?)",
                    [(l, f"T_{l}", T0 + timedelta(hours=h), s, v, b) for l, h, s, v, b in spike_rows])
    con.execute("CREATE TABLE views(lang VARCHAR, title VARCHAR, ts_hour_start TIMESTAMP, views INT, baseline_median DOUBLE)")
    con.executemany("INSERT INTO views VALUES (?, ?, ?, ?, ?)",
                    [(l, f"T_{l}", T0 + timedelta(hours=h), v, 10.0) for l, h, v in view_rows])
    con.execute("CREATE TABLE dims(qid BIGINT, entity_class VARCHAR, n_languages INT)")
    con.execute("INSERT INTO dims VALUES (1, 'human', 25)")
    return con


SPIKES = [("es", 0, 50, 500, 10), ("en", 2, 30, 300, 10), ("fr", 3, 20, 200, 10), ("de", 5, 9, 150, 10),
          ("it", 3, 7, 120, 10)]                      # it: below R3, counts for excess only
VIEWS = [("es", h, 500 - 40 * h) for h in range(0, 10)] + [("en", h, 300) for h in range(2, 6)] + \
        [("fr", 3, 200), ("de", 5, 150)]


def _rows(con, **kw):
    rel = con.sql(snapshot_sql("events", "spikes", "views", "dims", **kw) + " ORDER BY offset_h")
    return [dict(zip(rel.columns, r)) for r in rel.fetchall()]


def test_t0_is_the_second_language_and_features_use_only_the_past():
    rows = _rows(_con(SPIKES, VIEWS))
    by = {r["offset_h"]: r for r in rows}
    assert by[0]["t0"] == T0 + timedelta(hours=2)                 # en is the second language
    assert [by[k]["breadth_t"] for k in (0, 1, 3)] == [2, 3, 4]  # T = +2, +3, +5
    assert by[0]["max_surprise_t"] == 50 and by[0]["sum_surprise_t"] == 80
    assert by[0]["excess_t"] == 490 + 290                         # es + en rows up to T
    assert by[1]["excess_t"] == 490 + 290 + 190 + 110             # + fr and it (candidate, below R3) at +3
    assert by[0]["lead_share_t"] == 490 / 780
    assert by[0]["new_langs_last_hour"] == 1 and by[3]["new_langs_last_hour"] == 1
    assert by[0]["views_t"] == 300 + 420                          # en + es at +2 (es known since +0)
    assert by[0]["is_death"] == 1 and by[0]["n_sitelinks"] == 25 and by[0]["entity_class"] == "human"


def test_future_rows_never_change_features():
    base = _rows(_con(SPIKES, VIEWS))
    later = SPIKES + [("ja", 8, 999, 9999, 10), ("es", 6, 80, 900, 10)]
    more = _rows(_con(later, VIEWS + [("ja", 8, 9999), ("es", 11, 99999)]))
    cols = ["breadth_t", "max_surprise_t", "sum_surprise_t", "excess_t", "views_t", "peak_views_so_far"]
    for a, b in zip(base, more):
        assert {c: a[c] for c in cols} == {c: b[c] for c in cols}


def test_targets():
    rows = _rows(_con(SPIKES, VIEWS, breadth=6), targets=True, data_end="2026-12-31 00:00:00")
    r3 = [r for r in rows if r["offset_h"] == 3][0]               # T = +5
    assert r3["reach_international"] == 1 and r3["reach_planetary"] == 0
    # next 24 h after +5: es at +6..+9 (260, 220, 180, 140 views; baseline 10)
    assert r3["excess_next24"] == 250 + 210 + 170 + 130
    # peak = 500 + ... at +3? totals: +0 500, +2 720, +3 880, +4 640, +5 780 -> peak 880 at +3; half = 440
    assert r3["fade_hours"] == 1                                   # +6: 260 < 440
    assert r3["fade_observable"]
