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
    return [dict(zip(rel.columns, r, strict=True)) for r in rel.fetchall()]


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


def test_episodes_are_deterministic_with_simultaneous_spikes():
    """Several languages in the same hour must not split an episode, whatever the input order."""
    rows = [(1, l, 0, 20) for l in ("de", "en", "es")] + [(1, l, 30, 20) for l in ("de", "en", "es", "fr")]
    results = set()
    for order in (rows, rows[::-1], rows[3:] + rows[:3]):
        events, _ = _events(_spikes(order))
        results.add(tuple((e["start_hour"], e["breadth"]) for e in events))
    assert results == {((T0, 3), (T0 + timedelta(hours=30), 4))}


def test_single_language_events_are_classified():
    con = duckdb.connect()
    con.execute("CREATE TABLE spikes(qid INTEGER, lang VARCHAR, ts_hour_start TIMESTAMP, surprise DOUBLE, "
                "views INTEGER, baseline_median DOUBLE)")
    rows = [(1, "ja", 0, 6534, 63000, 50.0), (1, "en", 3, 50, 500, 100.0), (1, "zh", 4, 31, 300, 100.0),   # ja-only
            (2, "es", 0, 40, 5000, 100.0), (2, "en", 1, 30, 4000, 100.0), (2, "fr", 2, 20, 3000, 100.0)]  # shared
    con.executemany("INSERT INTO spikes VALUES (?, ?, ?, ?, ?, ?)",
                    [(q, l, T0 + timedelta(hours=h), s, v, b) for q, l, h, s, v, b in rows])
    events, _ = _events(con)
    cls = {e["qid"]: (e["event_class"], round(e["lead_excess_share"], 3)) for e in events}
    assert cls[1][0] == "single_language" and cls[1][1] >= 0.95
    assert cls[2][0] == "multi_language"


def test_tiers_follow_breadth():
    langs = ["en", "fr", "de", "es", "it", "ja", "zh", "ru", "pt", "pl", "nl", "ar", "fa", "tr", "id", "sv", "ko",
             "cs", "fi", "uk", "he"]
    rows = [(1, l, 0, 20) for l in langs[:2]] + [(2, l, 0, 20) for l in langs[:5]] + [(3, l, 1, 20) for l in langs[:20]]
    p = EventParams(min_languages=2, window_hours=6, breadth_hours=24, new_event_gap_hours=24, r3_threshold=8)
    events, _ = _events(_spikes(rows), p)
    assert {e["qid"]: (e["breadth"], e["tier"]) for e in events} == {
        1: (2, "noticed"), 2: (5, "international"), 3: (20, "planetary")}


def test_product_config_lowers_min_languages_only():
    from lookedup.analytics.config import load
    cfg = load()
    assert cfg.event.min_languages == 3                        # pre-registered primary, unchanged
    assert cfg.product_event.min_languages == 2
    assert cfg.product_event.window_hours == cfg.event.window_hours
    assert dict(cfg.tiers) == {"planetary": 20, "international": 5, "noticed": 2}


def test_spikes_without_a_qid_are_ignored():
    assert _events(_spikes([(None, "es", 0, 50), (None, "en", 1, 30), (None, "fr", 2, 30)]))[0] == []


def test_repeated_language_spikes_count_once():
    con = _spikes([(1, "es", 0, 20), (1, "es", 1, 60), (1, "es", 2, 15), (1, "en", 1, 30), (1, "fr", 2, 12)])
    [ev], _ = _events(con)
    langs = {r["lang"]: r for r in _dicts(build_events(con, "spikes", P)[1])}
    assert ev["breadth"] == 3 and ev["peak_intensity"] == 60
    assert langs["es"]["spike_hours"] == 3 and langs["es"]["peak_surprise"] == 60 and langs["es"]["first_spike"] == T0


def test_spikes_after_the_breadth_window_are_left_out():
    rows = [(1, l, h, 20) for l, h in [("en", 0), ("fr", 1), ("de", 2)]]
    rows += [(1, "it", h, 20) for h in range(10, 30, 4)]                 # keeps the episode alive past 24 h
    rows += [(1, "ja", 25, 20)]
    [ev], el = _events(_spikes(rows))
    assert ev["breadth"] == 4 and "ja" not in el and el["it"] == 10


def test_event_id_and_language_order():
    [ev], _ = _events(_spikes([(7, "fr", 2, 20), (7, "en", 0, 20), (7, "de", 2, 20), (7, "ja", 1, 20)]))
    assert ev["event_id"] == "Q7@20260810T12"
    assert ev["languages"] == ["en", "ja", "de", "fr"]                    # by lag, then by code


def test_excess_from_scored_hours():
    con = _spikes([(1, "es", 0, 50), (1, "en", 1, 30), (1, "fr", 2, 12)])
    con.execute("CREATE TABLE scored AS SELECT qid, lang, ts_hour_start + INTERVAL 1 HOUR AS ts_hour_start, 400 AS views, "
                "100.0 AS baseline_median FROM spikes")                      # the hour after each spike: 300 more views
    con.execute("INSERT INTO scored SELECT qid, lang, ts_hour_start, views, baseline_median FROM spikes")
    ev, _ = build_events(con, "spikes", P, scored="scored")
    [e] = _dicts(ev)
    assert e["excess_views"] == 3 * 900 + 3 * 300
    assert e["lead_excess_share"] == pytest.approx(1200 / 3600)


def test_breadth_matches_language_rows():
    con = _spikes([(1, "es", 0, 50), (1, "en", 1, 30), (1, "fr", 2, 12), (1, "de", 3, 9)])
    ev, el = build_events(con, "spikes", P)
    [e] = _dicts(ev)
    assert e["breadth"] == len(_dicts(el)) == 4


def test_two_qids_two_events():
    rows = [(q, l, h, 20) for q in (1, 2) for l, h in [("en", 0), ("fr", 1), ("de", 2)]]
    events, _ = _events(_spikes(rows))
    assert sorted(e["qid"] for e in events) == [1, 2]


def test_lead_is_a_member():
    [ev], el = _events(_spikes([(1, "ja", 0, 20), (1, "ko", 0, 25), (1, "zh", 1, 30)]))
    assert ev["lead_lang"] in el and el[ev["lead_lang"]] == 0


def test_threshold_is_inclusive():
    [ev], _ = _events(_spikes([(1, "es", 0, 8), (1, "en", 1, 8), (1, "fr", 2, 8)]))
    assert ev["breadth"] == 3
