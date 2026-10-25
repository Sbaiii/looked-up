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


def test_commit_gives_up_after_repeated_conflicts(tmp_path, monkeypatch):
    from lookedup.store import StoreConflict

    class Racy:
        def head(self):
            return "rev"

        def commit(self, *a, **k):
            raise StoreConflict("raced")

    monkeypatch.setattr(scorer.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="could not commit"):
        scorer._commit(Racy(), {}, "data: x")


def test_old_baselines_are_pruned(lake):
    bl = lake.root / "bl"
    bl.mkdir()
    old = scorer.baselines_file(D - timedelta(days=scorer.KEEP_BASELINE_DAYS + 1), bl)
    recent = scorer.baselines_file(D - timedelta(days=1), bl)
    old.write_bytes(b"old")
    recent.write_bytes(b"recent")
    scorer.build_baselines(lake, D, directory=bl)
    assert not old.exists() and recent.exists() and scorer.baselines_file(D, bl).exists()


def test_score_named_hours_only_if_present(lake):
    scorer.build_baselines(lake, D, directory=lake.root / "bl")
    present = datetime.combine(D, datetime.min.time()) + timedelta(hours=10)
    missing = datetime.combine(D, datetime.min.time()) + timedelta(hours=20)
    out = scorer.score(lake, now=present + timedelta(hours=4), langs=["en", "es", "fr"], hours=[missing, present],
                       baselines_dir=lake.root / "bl", recompute=False)
    assert out["scored_hours"] == [f"{present:%Y-%m-%dT%H}"]


def test_spike_file_merges_runs(lake):
    import pyarrow.parquet as pq

    scorer.build_baselines(lake, D, directory=lake.root / "bl")
    kw = {"langs": ["en", "es", "fr"], "baselines_dir": lake.root / "bl", "recompute": False}
    first = scorer.score(lake, now=datetime.combine(D, datetime.min.time()) + timedelta(hours=13), max_hours=11, **kw)
    second = scorer.score(lake, now=datetime.combine(D, datetime.min.time()) + timedelta(hours=14), max_hours=12, **kw)
    assert len(first["scored_hours"]) == 11 and second["scored_hours"] == [f"{D:%Y-%m-%d}T11"]
    t = pq.read_table(lake.root / scorer.spikes_path(D))
    keys = list(zip(t["lang"].to_pylist(), t["title"].to_pylist(), t["ts_hour_start"].to_pylist(), strict=True))
    assert len(keys) == len(set(keys))                                         # no hour written twice
    assert {k[2].hour for k in keys} == {9, 10, 11} and set(t["qid"].to_pylist()) == {42}


def test_baselines_skip_a_day_that_cannot_be_fetched(lake, monkeypatch):
    real = lake.fetch
    gone = scorer.day_path(datetime.combine(D - timedelta(days=2), datetime.min.time()))
    monkeypatch.setattr(lake, "fetch", lambda p, d, rev=None: None if p == gone else real(p, d, rev))
    assert scorer.build_baselines(lake, D, directory=lake.root / "bl")["day_files"] == 2


def test_qids_for_skips_items_without_the_sitelink(monkeypatch):
    class S:
        def get(self, url, params=None, timeout=None):
            return _WDR({"entities": {"Q1": {"sitelinks": {}}, "Q2": {"sitelinks": {"frwiki": {"title": "Deux"}}}}})

    monkeypatch.setattr(scorer, "session", lambda: S())
    monkeypatch.setattr(scorer.time, "sleep", lambda s: None)
    assert scorer.qids_for([("fr", "Un"), ("fr", "Deux")]) == {("fr", "Deux"): 2}


def test_spike_and_event_paths_match_days():
    d = date(2026, 1, 9)
    assert scorer.spikes_path(d).endswith("year=2026/month=01/day=09.parquet")
    assert scorer.events_path(d).replace("events", "spikes") == scorer.spikes_path(d)


def test_qids_for_nothing(monkeypatch):
    monkeypatch.setattr(scorer, "session", lambda: pytest.fail("no request expected"))
    assert scorer.qids_for([]) == {}


def test_labels_for_nothing(monkeypatch):
    monkeypatch.setattr(scorer, "session", lambda: pytest.fail("no request expected"))
    assert scorer.labels_for([], ["en"]) == {}
