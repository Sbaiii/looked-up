from __future__ import annotations

from datetime import datetime, timedelta

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from lookedup import app_export as ax

T0 = datetime(2026, 8, 17, 2)


def _ev(eid, qid, breadth, excess, lead="en", cls="multi_language", tier=None, start=T0):
    return {"event_id": eid, "qid": qid, "start_hour": start, "lead_lang": lead, "breadth": breadth,
            "peak_intensity": 50.0, "excess_views": excess, "max_spread_lag_hours": 2, "event_class": cls,
            "tier": tier or ("planetary" if breadth >= 20 else "international" if breadth >= 5 else "noticed")}


def _lang(eid, lang, excess, lag=0):
    return {"event_id": eid, "lang": lang, "first_spike": T0 + timedelta(hours=lag), "spread_lag_hours": lag,
            "peak_surprise": 20.0, "excess_views": excess}


def test_labels_and_urls():
    assert ax.label_from_title("Mike_Burton_(swimmer)") == "Mike Burton"
    assert ax.wiki_url("en", "What? (film)") == "https://en.wikipedia.org/wiki/What%3F_(film)"
    assert ax.wiki_url("ja", "白川英樹") == "https://ja.wikipedia.org/wiki/白川英樹"


def test_select_keeps_top_by_breadth_plus_each_language_top_and_singles(monkeypatch):
    monkeypatch.setattr(ax, "TOP_EVENTS", 2)
    monkeypatch.setattr(ax, "PER_LANGUAGE", 1)
    events = [_ev("a", 1, 9, 100), _ev("b", 2, 8, 100), _ev("c", 3, 2, 50), _ev("d", 4, 2, 10),
              _ev("s1", 5, 2, 999, lead="ja", cls="single_language"), _ev("s2", 6, 2, 5, lead="ja", cls="single_language")]
    langs = ax.group_langs([_lang("a", "en", 100), _lang("b", "en", 90), _lang("c", "fi", 50), _lang("d", "fi", 10)])
    multi, single = ax.select(events, langs)
    assert [e["event_id"] for e in multi] == ["a", "b", "c"]     # c is Finnish's top event
    assert [e["event_id"] for e in single] == ["s1", "s2"]


def test_summary_counts_all_events_by_tier_language_and_hour():
    events = [_ev("a", 1, 20, 100), _ev("b", 2, 5, 10, lead="fr"), _ev("s", 3, 2, 5, lead="ja", cls="single_language")]
    langs = ax.group_langs([_lang("a", "en", 60), _lang("a", "fr", 40), _lang("b", "fr", 10)])
    s = ax.summary(events, langs)
    assert s["tiers"] == {"noticed": 0, "international": 1, "planetary": 1} and s["single_language"] == 1
    assert s["hourly"][2] == 2
    assert s["languages"]["fr"] == {"events": 2, "lead": 1, "excess": 50, "only_here": 0}
    assert s["languages"]["ja"]["only_here"] == 1


def test_event_object_rows_follow_spread_order():
    e = ax.event_obj(_ev("a", 42, 3, 300), [_lang("a", "fr", 1, 2), _lang("a", "en", 1, 0)],
                     {"en": "Quake_X", "fr": "Séisme_X"}, [0] * 48, "disaster")
    assert e["qid"] == "Q42" and e["start"] == "2026-08-17T02:00Z" and e["tier"] == "noticed"
    assert [r["lang"] for r in e["langs"]] == ["en", "fr"] and e["labels"]["fr"] == "Séisme X"
    assert e["urls"]["en"] == "https://en.wikipedia.org/wiki/Quake_X"


def test_sparklines_sum_languages_and_leave_future_hours_empty(tmp_path):
    hours = [T0 + timedelta(hours=h) for h in range(-2, 3)]
    t = pa.table({"ts_hour_start": hours * 2, "lang": ["en"] * 5 + ["fr"] * 5, "title": ["Quake_X"] * 5 + ["Séisme_X"] * 5,
                  "views_desktop": [10] * 10, "views_mobile": [5] * 10})
    pq.write_table(t, tmp_path / "h.parquet")
    sp = ax.sparklines(duckdb.connect(), [tmp_path / "h.parquet"], [_ev("a", 42, 2, 1)],
                       {42: {"en": "Quake_X", "fr": "Séisme_X"}}, last_hour=T0 + timedelta(hours=2))
    s = sp["a"]
    assert len(s) == 48 and s[ax.SPARK_BEFORE] == 30 and s[ax.SPARK_BEFORE - 2] == 30
    assert s[0] == 0 and s[ax.SPARK_BEFORE + 2] == 30 and s[ax.SPARK_BEFORE + 3] is None


def test_stats_merge_replaces_days_and_keeps_ninety(monkeypatch):
    monkeypatch.setattr(ax, "STATS_DAYS", 2)
    day = lambda n: {"events": n, "single_language": 0, "tiers": {"noticed": n, "international": 0, "planetary": 0},
                     "hourly": [n] + [0] * 23, "languages": {"en": {"events": n, "lead": n, "excess": n, "only_here": 0}}}
    old = ax.stats_payload({"2026-10-07": day(1), "2026-10-08": day(2)}, T0, ["en"])
    new = ax._update_stats(old, {"2026-10-08": day(5), "2026-10-09": day(3)}, T0, ["en"])
    assert [r["day"] for r in new["timeline"]] == ["2026-10-08", "2026-10-09"]
    assert new["events"] == 8 and new["per_language"]["en"]["lead_share"] == 1.0
    assert new["schema_version"] == ax.SCHEMA_VERSION


def test_dump_writes_a_gzipped_twin(tmp_path):
    import gzip
    import json
    n = ax.dump({"schema_version": 1, "x": "é"}, tmp_path / "a.json")
    assert json.loads(gzip.decompress((tmp_path / "a.json.gz").read_bytes())) == {"schema_version": 1, "x": "é"}
    assert n == len((tmp_path / "a.json").read_bytes())
    assert set(ax.with_gz({"data/app/a.json": tmp_path / "a.json"})) == {"data/app/a.json", "data/app/a.json.gz"}
