from __future__ import annotations

from datetime import date, datetime, timedelta

import duckdb
import pytest

from lookedup.analytics.config import load
from lookedup.analytics.scoring import automation_flags_sql, observation_counts, scored_candidates_sql

CFG = load()
D = date(2026, 8, 12)  # a Wednesday, 34 days after the period start: full 28-day lookback


def _con(rows):
    """rows: (lang, title, ts, desktop, mobile) -> a stg_hourly-shaped view named stg."""
    con = duckdb.connect()
    con.execute("CREATE TABLE raw(lang VARCHAR, title VARCHAR, ts_hour_start TIMESTAMP, views_desktop INT, views_mobile INT)")
    con.executemany("INSERT INTO raw VALUES (?, ?, ?, ?, ?)", rows)
    con.execute("""CREATE VIEW stg AS SELECT ts_hour_start, ts_hour_start::DATE AS day, hour(ts_hour_start)::INT AS hour_of_day,
                   (isodow(ts_hour_start) - 1) IN (5, 6) AS is_weekend, lang, title, views_desktop, views_mobile,
                   views_desktop + views_mobile AS views,
                   views_mobile / (views_desktop + views_mobile)::DOUBLE AS mobile_share FROM raw""")
    con.execute("CREATE TABLE prior AS SELECT 'en' AS lang, 8.0 AS prior_median, 3.0 AS prior_mad")
    return con


def _at(day, hour):
    return datetime(day.year, day.month, day.day, hour)


def _score(con):
    rel = con.sql(scored_candidates_sql("stg", D, CFG, "prior"))
    return {r[rel.columns.index("title")]: dict(zip(rel.columns, r)) for r in rel.fetchall()}


def test_observation_counts():
    assert observation_counts(D, CFG) == {"all": 28, "weekend": 8, "weekday": 20}
    assert observation_counts(date(2026, 7, 16), CFG)["all"] == 7   # clipped at the period start


def test_baseline_pads_absent_days_with_zero_and_scores():
    rows = []
    for i in range(1, 29):
        d = D - timedelta(days=i)
        if d.weekday() < 5:
            rows.append(("en", "Steady", _at(d, 10), 5, 5))           # 10 views every weekday
            if i % 4 == 0:
                rows.append(("en", "Rare", _at(d, 10), 25, 25))       # present on 5 of 20 weekdays
    rows += [("en", "Steady", _at(D, 10), 100, 100), ("en", "Rare", _at(D, 10), 100, 100),
             ("en", "Unseen", _at(D, 10), 100, 100)]
    s = _score(_con(rows))
    st = s["Steady"]
    assert st["baseline_level"] == "day_type" and st["baseline_median"] == 10 and st["baseline_mad"] == 0
    assert st["surprise"] == pytest.approx(190 / (10 ** 0.5 + 1))
    assert st["r1"] and st["views_yesterday"] == 10
    assert s["Rare"]["baseline_median"] == 0 and s["Rare"]["surprise"] == 200   # mostly absent: median 0
    u = s["Unseen"]
    assert u["unseen"] and u["baseline_level"] == "prior" and u["baseline_median"] == 8
    assert not u["r1"]                                       # never R1 for unseen entities
    assert u["r2"]                                           # previous 3 hours absent -> 0


def test_r2_uses_previous_three_hours_including_yesterday():
    rows = [("en", "Night", _at(D - timedelta(days=1), 22), 60, 0), ("en", "Night", _at(D - timedelta(days=1), 23), 60, 0),
            ("en", "Night", _at(D, 0), 100, 50), ("en", "Night", _at(D, 1), 150, 50)]
    s = _score(_con(rows))
    assert s["Night"]["hour_of_day"] in (0, 1)
    con = _con(rows)
    rel = con.sql(scored_candidates_sql("stg", D, CFG, "prior") + " ORDER BY hour_of_day")
    rows_out = [dict(zip(rel.columns, r)) for r in rel.fetchall()]
    assert [r["prev3_median"] for r in rows_out] == [60, 60]   # (60, 60, 0) then (150, 60, 60)
    assert [r["r2"] for r in rows_out] == [False, True]


def test_automation_flags():
    rows = [("fr", "Cookie", _at(D, h), 100, 0) for h in range(24) if h % 3 == 0]          # desktop only
    rows += [("en", "Crawler", _at(D, h), 150, 100) for h in range(24)]                     # flat, 250/h
    rows += [("en", "Human", _at(D, h), 10, 40 + 10 * (h % 12)) for h in range(24)]        # mobile, diurnal
    con = _con(rows)
    rel = con.sql(automation_flags_sql("stg", D, CFG))
    f = {r[1]: dict(zip(rel.columns, r)) for r in rel.fetchall()}
    assert f["Cookie"]["is_low_mobile"] and f["Cookie"]["is_automated"]
    assert f["Crawler"]["is_flat"] and not f["Crawler"]["is_low_mobile"] and f["Crawler"]["is_automated"]
    assert not f["Human"]["is_automated"]
