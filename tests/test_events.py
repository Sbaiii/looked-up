from __future__ import annotations

from datetime import datetime, timedelta

import duckdb
import pytest

from lookedup.analytics.config import EventParams
from lookedup.analytics.events import build_events

T0 = datetime(2026, 8, 10, 12)
P = EventParams(min_languages=3, window_hours=6, breadth_hours=24, new_event_gap_hours=24, r3_threshold=8)


def _spikes(rows):
    con = duckdb.connect()
    con.execute("CREATE TABLE spikes(qid INTEGER, lang VARCHAR, ts_hour_start TIMESTAMP, surprise DOUBLE, "
                "views INTEGER, baseline_median DOUBLE)")
    con.executemany("INSERT INTO spikes VALUES (?, ?, ?, ?, ?, ?)",
                    [(q, l, T0 + timedelta(hours=h), s, 1000, 100.0) for q, l, h, s in rows])
    return con


def _dicts(rel):
    return [dict(zip(rel.columns, r)) for r in rel.fetchall()]


def _events(con, p=P):
    ev, el = build_events(con, "spikes", p)
    langs = _dicts(el)
    return sorted(_dicts(ev), key=lambda e: e["start_hour"]), {r["lang"]: r["spread_lag_hours"] for r in langs}


def test_three_languages_within_window_make_an_event():
    con = _spikes([(1, "es", 0, 50), (1, "en", 1, 30), (1, "fr", 5, 12), (1, "de", 20, 9)])
    [ev], el = _events(con)
    assert ev["start_hour"] == T0 and ev["lead_lang"] == "es"
    assert ev["breadth"] == 4                       # de spikes within 24 h of start
    assert ev["peak_intensity"] == 50
    assert el == {"es": 0, "en": 1, "fr": 5, "de": 20}
    assert ev["median_spread_lag_hours"] == 5        # median over non-lead languages (1, 5, 20)
    assert ev["excess_views"] == 4 * 900


def test_two_languages_or_too_spread_out_is_no_event():
    assert _events(_spikes([(1, "es", 0, 50), (1, "en", 1, 30)]))[0] == []
    assert _events(_spikes([(1, "es", 0, 50), (1, "en", 3, 30), (1, "fr", 6, 30)]))[0] == []  # [0, 6) holds 2


def test_low_surprise_spikes_are_ignored():
    assert _events(_spikes([(1, "es", 0, 50), (1, "en", 1, 30), (1, "fr", 2, 7.9)]))[0] == []


def test_gap_of_24h_starts_a_new_event_and_windows_merge():
    rows = [(1, l, h, 20) for l, h in [("en", 0), ("fr", 1), ("de", 2), ("it", 4), ("es", 7)]]
    rows += [(1, l, h, 20) for l, h in [("en", 40), ("fr", 41), ("ja", 42)]]
    events, _ = _events(_spikes(rows))
    assert [e["start_hour"] for e in events] == [T0, T0 + timedelta(hours=40)]
    assert events[0]["breadth"] == 5


def test_lead_tie_breaks_on_surprise_then_alphabet():
    [ev], _ = _events(_spikes([(1, "fr", 0, 20), (1, "de", 0, 20), (1, "en", 0, 10), (1, "ja", 1, 99)]))
    assert ev["lead_lang"] == "de"


@pytest.mark.parametrize("min_langs,expected", [(2, 1), (3, 1), (5, 0)])
def test_ablation_parameters(min_langs, expected):
    con = _spikes([(1, "es", 0, 50), (1, "en", 1, 30), (1, "fr", 2, 12)])
    p = EventParams(min_languages=min_langs, window_hours=6, breadth_hours=24, new_event_gap_hours=24, r3_threshold=8)
    assert len(_events(con, p)[0]) == expected
