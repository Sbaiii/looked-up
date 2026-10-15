from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pyarrow as pa
import pytest

from lookedup import scorer
from lookedup.store import LocalStore, write_hours
from lookedup.transform import SCHEMA

D = date(2026, 9, 2)


def _hour(ts, rows):
    return pa.table({"ts_hour_start": [ts] * len(rows), "lang": [r[0] for r in rows], "title": [r[1] for r in rows],
                     "views_desktop": [r[2] for r in rows], "views_mobile": [r[3] for r in rows]}).cast(SCHEMA)


@pytest.fixture
def lake(tmp_path, monkeypatch):
    store = LocalStore(tmp_path / "lake")
    tables = {}
    for k in range(1, 4):  # three quiet days of background traffic
        for h in range(24):
            ts = datetime.combine(D - timedelta(days=k), datetime.min.time()) + timedelta(hours=h)
            tables[ts] = (_hour(ts, [("en", "Background", 20, 30)]), "hourly_dump")
    burst = {9: [("es", "Sismo_X", 50, 900)], 10: [("en", "Quake_X", 100, 1500), ("es", "Sismo_X", 40, 700)],
             11: [("fr", "Séisme_X", 30, 400), ("en", "Quake_X", 80, 900)]}
    for h in range(12):
        ts = datetime.combine(D, datetime.min.time()) + timedelta(hours=h)
        tables[ts] = (_hour(ts, [("en", "Background", 20, 30)] + burst.get(h, [])), "hourly_dump")
    write_hours(store, tables, "seed")
    monkeypatch.setattr(scorer, "qids_for", lambda keys: {k: 42 for k in keys if k[1] != "Background"})
    monkeypatch.setattr(scorer, "labels_for", lambda q, langs: {42: {"en": "Quake X", "es": "Sismo X", "fr": "Séisme X"}})
    monkeypatch.setattr(scorer, "fetch_claims", lambda q, cache: pa.table({"qid": [42], "label_en": ["Quake X"],
                        "claims_json": [json.dumps({"P31": [7944]})]}))
    return store


def test_baselines_then_score_produces_an_event(lake):
    res = scorer.build_baselines(lake, D, directory=lake.root / "bl")
    assert res["day_files"] == 3 and scorer.baselines_file(D, lake.root / "bl").exists()
    assert not (lake.root / "data" / "baselines").exists()          # never written to the lake
    now = datetime.combine(D, datetime.min.time()) + timedelta(hours=14)
    out = scorer.score(lake, now=now, max_hours=12, langs=["en", "es", "fr"], baselines_dir=lake.root / "bl",
                       recompute=False)
    assert len(out["scored_hours"]) == 12
    latest = json.loads((lake.root / scorer.LATEST_PATH).read_text())
    [ev] = latest["events"]
    assert ev["qid"] == "Q42" and ev["lead_lang"] == "es" and ev["breadth"] == 3 and ev["tier"] == "noticed"
    assert ev["category"] == "disaster" and ev["labels"]["fr"] == "Séisme X"
    assert (lake.root / scorer.events_path(D)).exists() and (lake.root / scorer.spikes_path(D)).exists()
    # idempotent: a second run has nothing new to score
    assert scorer.score(lake, now=now, max_hours=12, langs=["en", "es", "fr"], baselines_dir=lake.root / "bl",
                        recompute=False)["scored_hours"] == []


def test_score_waits_for_baselines_or_recomputes_one_day(lake):
    now = datetime.combine(D, datetime.min.time()) + timedelta(hours=14)
    bl = lake.root / "bl"
    assert scorer.score(lake, now=now, max_hours=6, langs=["en", "es", "fr"], baselines_dir=bl,
                        recompute=False)["scored_hours"] == []
    out = scorer.score(lake, now=now, max_hours=6, langs=["en", "es", "fr"], baselines_dir=bl)   # recompute on miss
    assert out["scored_hours"][0] == f"{D:%Y-%m-%d}T00"
    assert scorer.baselines_file(D, bl).exists()


def test_bucketed_baselines_equal_single_pass():
    """Building baselines in hash buckets gives exactly the single-pass result."""
    import duckdb

    from lookedup.analytics.config import load
    from lookedup.analytics.production import daily_baselines_sql

    cfg = load()
    con = duckdb.connect()
    con.execute("""CREATE TABLE src AS
        SELECT TIMESTAMP '2026-09-02 00:00' - to_days(d) + to_hours(h) AS ts_hour_start,
               (TIMESTAMP '2026-09-02 00:00' - to_days(d))::DATE AS day, h AS hour_of_day,
               (isodow(TIMESTAMP '2026-09-02 00:00' - to_days(d)) - 1) IN (5, 6) AS is_weekend,
               'en' AS lang, 'T' || t AS title, 5 + (t * 7 + d * 3 + h) % 40 AS views
        FROM range(1, 29) r1(d), range(0, 24, 6) r2(h), range(0, 40) r3(t)""")
    one = set(con.sql(daily_baselines_sql("src", D, cfg)).fetchall())
    many = set()
    for i in range(4):
        many |= set(con.sql(daily_baselines_sql("src", D, cfg, bucket=(i, 4), include_prior=(i == 0))).fetchall())
    assert len(one) > 100 and one == many


def test_lake_paths_mirror_the_day_layout(tmp_path):
    d = date(2026, 8, 17)
    assert scorer.spikes_path(d) == "data/spikes/year=2026/month=08/day=17.parquet"
    assert scorer.events_path(d) == "data/events/year=2026/month=08/day=17.parquet"
    assert scorer.event_languages_path(d) == "data/events/languages/year=2026/month=08/day=17.parquet"
    assert scorer.baselines_file(d, tmp_path) == tmp_path / "day=2026-08-17.parquet"


class _WDR:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def test_qids_for_maps_titles_through_sitelinks(monkeypatch):
    calls = []

    class S:
        def get(self, url, params=None, timeout=None):
            calls.append(params)
            return _WDR({"entities": {"Q597": {"sitelinks": {"enwiki": {"title": "Lisbon"}}}, "-1": {"missing": ""}}})

    monkeypatch.setattr(scorer, "session", lambda: S())
    monkeypatch.setattr(scorer.time, "sleep", lambda s: None)
    titles = [("en", "Lisbon")] + [("en", f"T_{i}") for i in range(60)]
    assert scorer.qids_for(titles) == {("en", "Lisbon"): 597}
    assert [c["titles"].count("|") + 1 for c in calls] == [50, 11]
    assert "T 0" in calls[0]["titles"]                                  # underscores become spaces for the API


def test_labels_for_keeps_active_languages(monkeypatch):
    class S:
        def get(self, url, params=None, timeout=None):
            return _WDR({"entities": {"Q597": {"sitelinks": {"enwiki": {"title": "Lisbon"}, "ptwiki": {"title": "Lisboa"},
                                                             "commonswiki": {"title": "Category:Lisbon"}}}}})

    monkeypatch.setattr(scorer, "session", lambda: S())
    monkeypatch.setattr(scorer.time, "sleep", lambda s: None)
    assert scorer.labels_for([597], ["en", "pt"]) == {597: {"en": "Lisbon", "pt": "Lisboa"}}


def test_baselines_need_day_files(tmp_path):
    with pytest.raises(RuntimeError, match="no day files"):
        scorer.build_baselines(LocalStore(tmp_path / "empty"), date(2026, 8, 17), tmp_path / "b")
