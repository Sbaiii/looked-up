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
    monkeypatch.setattr(ax, "TOP_BY_EXCESS", 0)
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


def test_descriptions_are_short_ui_languages_only_and_gender_is_kept():
    long = "x" * 120
    e = ax.event_obj(_ev("a", 42, 3, 300), [_lang("a", "en", 1)], {"en": "Quake_X"}, None, "human",
                     ({"en": "American actress", "fr": long, "ja": "女優"}, "female"))
    assert e["desc"]["en"] == "American actress" and "ja" not in e["desc"]
    assert len(e["desc"]["fr"]) == ax.DESC_MAX and e["desc"]["fr"].endswith("…")
    assert e["gender"] == "female"
    assert "gender" not in ax.event_obj(_ev("b", 7, 3, 1), [], {}, None, None, ({}, None))


def test_select_keeps_the_biggest_excess_even_with_low_breadth(monkeypatch):
    monkeypatch.setattr(ax, "TOP_EVENTS", 1)
    monkeypatch.setattr(ax, "TOP_BY_EXCESS", 1)
    monkeypatch.setattr(ax, "PER_LANGUAGE", 0)
    events = [_ev("wide", 1, 9, 10), _ev("big", 2, 2, 5_000_000), _ev("small", 3, 2, 5)]
    multi, _ = ax.select(events, {})
    assert {e["event_id"] for e in multi} == {"wide", "big"}


def test_events_group_by_their_utc_start_date():
    e = lambda i, h: {"event_id": f"E{i}", "start_hour": datetime(2026, 8, 17) + timedelta(hours=h)}
    days = ax.by_day([e(1, 2), e(2, 23), e(3, 24), e(4, -1)])
    assert sorted(days) == [datetime(2026, 8, 16).date(), datetime(2026, 8, 17).date(), datetime(2026, 8, 18).date()]
    assert [x["event_id"] for x in days[datetime(2026, 8, 17).date()]] == ["E1", "E2"]


def test_short_descriptions():
    assert ax.short("x" * ax.DESC_MAX) == "x" * ax.DESC_MAX
    cut = ax.short("word " * 40)
    assert len(cut) <= ax.DESC_MAX and cut.endswith("…") and not cut[:-1].endswith(" ")


def test_day_and_card_paths():
    d = datetime(2026, 8, 17).date()
    assert ax.day_file(d) == f"{ax.APP_PREFIX}/days/2026-08-17.json"
    assert ax.og_file(d) == f"{ax.APP_PREFIX}/og/2026-08-17.png"


def _day_summary(n, lead_lang="en"):
    return {"tiers": {"noticed": n, "international": 0, "planetary": 0}, "single_language": 1,
            "languages": {lead_lang: {"events": n, "lead": n}}, "hourly": [0] * 24, "events": n}


def test_stats_keep_the_last_90_days():
    start = datetime(2026, 7, 1)
    days = {f"{start + timedelta(days=i):%Y-%m-%d}": _day_summary(1) for i in range(100)}
    s = ax.stats_payload(days, datetime(2026, 10, 9), ["en"])
    assert len(s["timeline"]) == ax.STATS_DAYS == len(s["days"])
    assert s["first_day"] == f"{start + timedelta(days=10):%Y-%m-%d}" and s["last_day"] == f"{start + timedelta(days=99):%Y-%m-%d}"
    assert s["events"] == 90 and s["single_language"] == 90


def test_stats_lead_share():
    days = {"2026-08-16": _day_summary(3, "en"), "2026-08-17": _day_summary(1, "ja")}
    s = ax.stats_payload(days, datetime(2026, 8, 18), ["en", "ja"])
    assert s["per_language"]["en"]["lead_share"] == 0.75 and s["per_language"]["ja"]["lead_share"] == 0.25
    assert s["tiers"] == {"noticed": 4, "international": 0, "planetary": 0}
    assert "forecast" not in s
    assert ax.stats_payload({}, datetime(2026, 8, 18), [])["first_day"] is None


def test_stats_update_merges_days_and_keeps_the_forecast():
    old = ax.stats_payload({"2026-08-16": _day_summary(2)}, datetime(2026, 8, 17), ["en"], forecast={"auc": 0.875})
    new = ax._update_stats(old, {"2026-08-17": _day_summary(5)}, datetime(2026, 8, 18), ["en"])
    assert sorted(new["days"]) == ["2026-08-16", "2026-08-17"] and new["events"] == 7
    assert new["forecast"] == {"auc": 0.875}
    stale = dict(old, schema_version=ax.SCHEMA_VERSION - 1)
    assert sorted(ax._update_stats(stale, {"2026-08-17": _day_summary(5)}, datetime(2026, 8, 18), ["en"])["days"]) == ["2026-08-17"]


def test_texts_from_table():
    t = pa.table({"qid": [1, 2], "descriptions_json": ['{"en": "capital of Portugal"}', None], "gender": [None, "female"]})
    assert ax.texts_from_table(t) == {1: ({"en": "capital of Portugal"}, None), 2: ({}, "female")}


def test_categories_mark_recent_deaths(monkeypatch):
    import json

    import lookedup.analytics.entities as E

    claims = pa.table({"qid": [1, 2, 3], "label_en": ["A", "B", "C"],
                       "claims_json": [json.dumps({"P31": [5], "P570": ["2026-08-16"]}),
                                       json.dumps({"P31": [5], "P570": ["2001-01-01"]}), json.dumps({"P31": [515]})]})
    monkeypatch.setattr(E, "fetch_claims", lambda qids, cache: claims)
    start = datetime(2026, 8, 17, 2)
    cats = ax.categories_for([{"qid": q, "start_hour": start} for q in (1, 2, 3)])
    assert cats[1] == "death" and cats[2] == "human" and cats[3] != "death"
    assert ax.categories_for([]) == {}


def test_single_language_events_capped_per_lead(monkeypatch):
    monkeypatch.setattr(ax, "SINGLE_PER_LANGUAGE", 2)
    singles = [{"event_id": f"S{i}", "event_class": "single_language", "lead_lang": "ja", "excess_views": i, "breadth": 1}
               for i in range(5)] + [{"event_id": "F", "event_class": "single_language", "lead_lang": "fr", "excess_views": 1, "breadth": 1}]
    _, kept = ax.select(singles, {})
    assert [e["event_id"] for e in kept] == ["S4", "S3", "F"]


def test_events_from_spikes(tmp_path):
    h = datetime(2026, 8, 17, 2)
    rows = {"qid": [597, 597, 597, 9], "lang": ["en", "pt", "fr", "en"],
            "ts_hour_start": [h, h + timedelta(hours=1), h + timedelta(hours=2), h],
            "title": ["Lisbon", "Lisboa", "Lisbonne", "Lone"], "surprise": [50.0, 30.0, 12.0, 90.0],
            "views": [5000, 3000, 900, 800], "baseline_median": [100.0, 50.0, 30.0, 10.0],
            "is_automated": [False, False, False, False]}
    f = tmp_path / "spikes.parquet"
    pq.write_table(pa.table(rows), f)
    events, langs = ax.events_from_spikes(duckdb.connect(), [f])
    multi = [e for e in events if e["qid"] == 597]
    assert len(multi) == 1 and multi[0]["breadth"] == 3 and multi[0]["lead_lang"] == "en"
    assert multi[0]["start_hour"] == h and multi[0]["tier"] == "noticed"
    assert sorted(r["lang"] for r in langs if r["event_id"] == multi[0]["event_id"]) == ["en", "fr", "pt"]
    assert not [e for e in events if e["qid"] == 9]                    # one language is not an event
    assert ax.events_from_spikes(duckdb.connect(), []) == ([], [])


def test_titles_from_sitelinks(tmp_path):
    sl = tmp_path / "sitelinks.parquet"
    pq.write_table(pa.table({"lang": ["en", "pt", "ja", "en"], "title": ["Lisbon", "Lisboa", "リスボン", "Porto"],
                             "qid": [597, 597, 597, 36433]}), sl)
    got = ax.titles_from_sitelinks(duckdb.connect(), sl, {597}, ["en", "pt"])
    assert got == {597: {"en": "Lisbon", "pt": "Lisboa"}}


def _hourly_file(tmp_path, rows):
    f = tmp_path / "day.parquet"
    pq.write_table(pa.table({"ts_hour_start": [r[0] for r in rows], "lang": [r[1] for r in rows],
                             "title": [r[2] for r in rows], "views_desktop": [r[3] for r in rows],
                             "views_mobile": [0] * len(rows)}), f)
    return f


def test_sparklines_place_hours_around_the_start(tmp_path):
    start = datetime(2026, 8, 17, 12)
    f = _hourly_file(tmp_path, [(start, "en", "Lisbon", 100), (start, "pt", "Lisboa", 50),
                                (start - timedelta(hours=1), "en", "Lisbon", 10), (start, "en", "Other", 999)])
    ev = {"event_id": "E1", "qid": 597, "start_hour": start}
    sp = ax.sparklines(duckdb.connect(), [f], [ev], {597: {"en": "Lisbon", "pt": "Lisboa"}})["E1"]
    assert len(sp) == ax.SPARK_HOURS
    assert sp[ax.SPARK_BEFORE] == 150 and sp[ax.SPARK_BEFORE - 1] == 10 and sum(sp) == 160


def test_sparkline_future_hours_are_unknown(tmp_path):
    start = datetime(2026, 8, 17, 12)
    f = _hourly_file(tmp_path, [(start, "en", "Lisbon", 100)])
    ev = {"event_id": "E1", "qid": 597, "start_hour": start}
    sp = ax.sparklines(duckdb.connect(), [f], [ev], {597: {"en": "Lisbon"}}, last_hour=start + timedelta(hours=2))["E1"]
    assert sp[ax.SPARK_BEFORE + 2] == 0 and sp[ax.SPARK_BEFORE + 3] is None and sp[-1] is None
    assert ax.sparklines(duckdb.connect(), [], [ev], {}) == {}


def test_live_forecasts_never_fail(tmp_path, monkeypatch):
    import lookedup.forecast.predict as P

    def broken(store, tmp):
        raise RuntimeError("corrupt model file")

    monkeypatch.setattr(P, "load_models", broken)
    assert ax.live_forecasts(duckdb.connect(), None, [], datetime(2026, 8, 17), None, [], {}, tmp_path) == ({}, {})


def test_export_live_end_to_end(tmp_path, monkeypatch):
    import json

    from lookedup.scorer import spikes_path
    from lookedup.store import LocalStore, Manifest, day_path

    now = datetime(2026, 8, 17, 14, 30)
    h = datetime(2026, 8, 17, 10)
    lake = tmp_path / "lake"
    spikes = {"qid": [597, 597], "lang": ["en", "pt"], "ts_hour_start": [h, h], "title": ["Lisbon", "Lisboa"],
              "surprise": [50.0, 30.0], "views": [5000, 3000], "baseline_median": [100.0, 50.0], "is_automated": [False, False]}
    (lake / spikes_path(h.date())).parent.mkdir(parents=True)
    pq.write_table(pa.table(spikes), lake / spikes_path(h.date()))
    hourly = lake / day_path(h)
    hourly.parent.mkdir(parents=True)
    pq.write_table(pa.table({"ts_hour_start": [h, h], "lang": ["en", "pt"], "title": ["Lisbon", "Lisboa"],
                             "views_desktop": [4000, 2000], "views_mobile": [1000, 1000]}), hourly)
    store = LocalStore(lake)
    m = Manifest()
    m.add(h, rows=2, source="hourly_dump")
    store.commit({}, m, "seed manifest")
    monkeypatch.setattr(ax, "titles_from_api", lambda qids, langs: {597: {"en": "Lisbon", "pt": "Lisboa"}})
    monkeypatch.setattr(ax, "categories_for", lambda events: {597: "place"})
    monkeypatch.setattr(ax, "texts_live", lambda events: {597: ({"en": "capital of Portugal"}, None)})
    res = ax.export_live(store, now=now, languages=["en", "pt"])
    assert res == {"today_events": 1, "days": ["2026-08-16", "2026-08-17"]}
    today = json.loads((lake / ax.APP_PREFIX / "today.json").read_text())
    assert [e["qid"] for e in today["events"]] == ["Q597"] and today["events"][0]["desc"] == {"en": "capital of Portugal"}
    assert (lake / ax.APP_PREFIX / "today.json.gz").exists() and (lake / ax.og_file(h.date())).exists()
    stats = json.loads((lake / ax.APP_PREFIX / "stats.json").read_text())
    assert sorted(stats["days"]) == ["2026-08-16", "2026-08-17"] and stats["events"] == 1


def test_titles_from_api_use_underscores(monkeypatch):
    import lookedup.scorer as S

    seen = []
    monkeypatch.setattr(S, "labels_for", lambda qids, langs: seen.append((qids, langs)) or {7: {"en": "New York City", "fr": "New York"}})
    assert ax.titles_from_api({9, 7}, ["en", "fr"]) == {7: {"en": "New_York_City", "fr": "New_York"}}
    assert seen == [([7, 9], ["en", "fr"])]


def test_texts_live_fetches_for_event_qids(monkeypatch):
    import lookedup.analytics.entities as E
    import lookedup.languages as L

    calls = []

    def fetch_text(qids, path, langs):
        calls.append((qids, path.name, langs))
        return pa.table({"qid": [5], "descriptions_json": ['{"fr": "ville"}'], "gender": [None]})

    monkeypatch.setattr(E, "fetch_text", fetch_text)
    monkeypatch.setattr(L, "active_codes", lambda: ["en", "fr"])
    assert ax.texts_live([]) == {} and calls == []
    assert ax.texts_live([{"qid": 5}, {"qid": 5}]) == {5: ({"fr": "ville"}, None)}
    assert calls == [({5}, "entity_text.parquet", ["en", "fr"])]


def test_event_object_carries_a_forecast_only_when_given():
    langs, titles = [_lang("a", "en", 1)], {"en": "Quake_X"}
    fc = {"p_international": 0.42, "excess_next24": 1200}
    assert ax.event_obj(_ev("a", 42, 3, 300), langs, titles, None, None, forecast=fc)["forecast"] == fc
    plain = ax.event_obj(_ev("a", 42, 3, 300), langs, titles, None, None)
    assert "forecast" not in plain and plain["category"] == "other"


def test_live_forecasts_empty_without_models_or_hour(tmp_path, monkeypatch):
    import lookedup.forecast.predict as P

    monkeypatch.setattr(P, "load_models", lambda store, tmp: ({"trained": "2026-10-05"}, {}))
    assert ax.live_forecasts(duckdb.connect(), None, [], T0, T0, [], {}, tmp_path) == ({}, {"trained": "2026-10-05"})
    monkeypatch.setattr(P, "load_models", lambda store, tmp: ({"trained": "2026-10-05"}, {"m": object()}))
    assert ax.live_forecasts(duckdb.connect(), None, [], T0, None, [], {}, tmp_path) == ({}, {"trained": "2026-10-05"})


def test_live_forecasts_for_open_events(tmp_path, monkeypatch):
    import lookedup.forecast.predict as P

    now = T0 + timedelta(hours=6)
    events = [_ev("open", 1, 3, 300), _ev("solo", 2, 1, 50, cls="single_language"),
              _ev("old", 3, 4, 900, start=now - timedelta(hours=30))]
    seen = {}
    monkeypatch.setattr(P, "load_models", lambda store, tmp: ({"version": "v9"}, {"m": object()}))
    monkeypatch.setattr(P, "entity_classes", lambda qids: seen.setdefault("classes", qids) and {1: "human"})
    monkeypatch.setattr(P, "live_relations", lambda con, ev, cats, cls, titles, files: seen.update(ev=[e["event_id"] for e in ev], titles=titles, cats=cats))
    monkeypatch.setattr(P, "forecast_open", lambda con, ev, n, last, manifest, models: {"open": {"p_international": 0.3}})
    monkeypatch.setattr(ax, "categories_for", lambda ev: {1: "human"})
    monkeypatch.setattr(ax, "_languages", lambda: ["en", "fr"])
    monkeypatch.setattr(ax, "titles_from_api", lambda qids, langs: {q: {"en": f"T{q}"} for q in qids})
    out = ax.live_forecasts(duckdb.connect(), None, events, now, now, [], {}, tmp_path)
    assert out == ({"open": {"p_international": 0.3}}, {"version": "v9"})
    assert seen["ev"] == ["open"] and seen["classes"] == {1} and seen["titles"] == {1: {"en": "T1"}}


def test_export_languages_are_active_codes(monkeypatch):
    import lookedup.languages as L

    monkeypatch.setattr(L, "active_codes", lambda: ["en", "ja"])
    assert ax._languages() == ["en", "ja"]


def test_sparklines_without_any_title(tmp_path):
    f = tmp_path / "h.parquet"
    pq.write_table(pa.table({"ts_hour_start": [T0], "lang": ["en"], "title": ["X"], "views_desktop": [1], "views_mobile": [1]}), f)
    sparks = ax.sparklines(duckdb.connect(), [f], [_ev("a", 42, 3, 300)], {}, last_hour=T0)
    assert set(sparks) == {"a"} and sparks["a"][ax.SPARK_BEFORE] == 0
def test_backfill_warehouse_then_live_days(tmp_path, monkeypatch):
    import json

    import lookedup.settings as S
    import lookedup.warehouse as W
    from lookedup.scorer import spikes_path
    from lookedup.store import LocalStore, day_path

    wh_day, live_h = datetime(2026, 8, 15, 9), datetime(2026, 8, 16, 10)
    wh = tmp_path / "w.duckdb"
    con = duckdb.connect(str(wh))
    con.execute("""CREATE TABLE fct_app_events AS SELECT 'E1' AS event_id, 1::BIGINT AS qid, TIMESTAMP '2026-08-15 09:00' AS start_hour,
        'en' AS lead_lang, 2 AS breadth, 40.0::DOUBLE AS peak_intensity, 900.0::DOUBLE AS excess_views, 1 AS max_spread_lag_hours,
        'multi_language' AS event_class, 'noticed' AS tier, 'human' AS category""")
    con.execute("""CREATE TABLE fct_app_event_languages AS SELECT * FROM (VALUES
        ('E1', 'en', TIMESTAMP '2026-08-15 09:00', 0, 40.0::DOUBLE, 600.0::DOUBLE),
        ('E1', 'fr', TIMESTAMP '2026-08-15 10:00', 1, 20.0::DOUBLE, 300.0::DOUBLE))
        t(event_id, lang, first_spike, spread_lag_hours, peak_surprise, excess_views)""")
    con.execute("CREATE TABLE dim_entities AS SELECT 1::BIGINT AS qid, '{\"en\": \"a person\"}' AS descriptions_json, 'female' AS gender")
    con.close()
    local = tmp_path / "mirror"
    (local / "data" / "wikidata").mkdir(parents=True)
    pq.write_table(pa.table({"qid": [1, 1], "lang": ["en", "fr"], "title": ["Ada", "Ada_fr"]}), local / "data/wikidata/sitelinks.parquet")
    for h in (wh_day, live_h):
        (local / day_path(h)).parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table({"ts_hour_start": [h], "lang": ["en"], "title": ["Ada"], "views_desktop": [10], "views_mobile": [5]}),
                       local / day_path(h))
    lake = tmp_path / "lake"
    (lake / spikes_path(live_h.date())).parent.mkdir(parents=True)
    pq.write_table(pa.table({"qid": [597, 597], "lang": ["en", "pt"], "ts_hour_start": [live_h, live_h], "title": ["Lisbon", "Lisboa"],
                             "surprise": [50.0, 30.0], "views": [5000, 3000], "baseline_median": [100.0, 50.0],
                             "is_automated": [False, False]}), lake / spikes_path(live_h.date()))
    monkeypatch.setattr(W, "WAREHOUSE_DB", wh)
    monkeypatch.setattr(S, "LOCAL_LAKE_DIR", local)
    monkeypatch.setattr(ax, "categories_for", lambda events: {597: "place"})
    monkeypatch.setattr(ax, "texts_live", lambda events: {597: ({"en": "capital of Portugal"}, None)})
    out = tmp_path / "out"
    res = ax.backfill(LocalStore(lake), out, now=datetime(2026, 8, 16, 14, 30), languages=["en", "fr", "pt"])
    assert (res["days"], res["first"], res["last"], res["events"]) == (2, "2026-08-15", "2026-08-16", 2)
    stats = json.loads((out / ax.APP_PREFIX / "stats.json").read_text())
    assert sorted(stats["days"]) == ["2026-08-15", "2026-08-16"]
    today = json.loads((out / ax.APP_PREFIX / "today.json").read_text())
    assert {e["qid"] for e in today["events"]} >= {"Q597"}


def test_gzip_twin_is_deterministic(tmp_path):
    ax.dump({"schema_version": 1, "events": [1, 2, 3]}, tmp_path / "a.json")
    first = (tmp_path / "a.json.gz").read_bytes()
    ax.dump({"schema_version": 1, "events": [1, 2, 3]}, tmp_path / "a.json")
    assert (tmp_path / "a.json.gz").read_bytes() == first


def test_event_object_fills_missing_numbers():
    e = _ev("a", 42, 3, None) | {"max_spread_lag_hours": None, "peak_intensity": 12.345}
    obj = ax.event_obj(e, [_lang("a", "fr", None, 1) | {"peak_surprise": 9.87}], {"fr": "Séisme_X", "en": "Quake_X"}, None, None)
    assert obj["excess"] == 0 and obj["spread_h"] == 0 and obj["peak"] == 12.3
    assert list(obj["labels"]) == ["en", "fr"] and obj["langs"][0] == {"lang": "fr", "first": "2026-08-17T03:00Z", "lag": 1,
                                                                      "surprise": 9.9, "excess": 0}
