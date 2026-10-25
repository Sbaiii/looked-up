from __future__ import annotations

from datetime import UTC, datetime, timedelta

from lookedup import live_analysis as LA

T0 = datetime(2026, 9, 20, 12)


def rev(minutes, user, tags=(), comment="", parent=1):
    return {"timestamp": f"{T0 + timedelta(minutes=minutes):%Y-%m-%dT%H:%M:%SZ}", "user": user, "tags": list(tags),
            "comment": comment, "parentid": parent}


def test_revision_filter():
    assert LA.counted(rev(0, "Alice"))
    assert not LA.counted(rev(0, "CleanupBot")) and not LA.counted(rev(0, "a", tags=["mw-reverted"]))
    assert not LA.counted(rev(0, "a", comment="Undid revision 1 by X"))


def test_burst_time_uses_the_live_rule_and_window():
    revs = [rev(m, u) for m, u in [(0, "a"), (5, "b"), (6, "bot2Bot"), (10, "a"), (12, "c"), (14, "b")]]
    ts, kind = LA.burst_time(revs, "en", "X", T0 - timedelta(hours=1), T0 + timedelta(hours=1))
    assert kind == "window" and ts == (T0 + timedelta(minutes=14)).replace(tzinfo=UTC).timestamp()
    assert LA.burst_time(revs, "en", "X", T0 + timedelta(hours=1), T0 + timedelta(hours=2)) == (None, None)


def test_h10_precision_needs_100_live_events():
    rows = [{"kind": "live", "hit": 1, "forward_hit": 0}] * 40 + [{"kind": "live", "hit": 0, "forward_hit": 0}] * 50 + \
           [{"kind": "single", "hit": 0, "forward_hit": 0}] * 10
    p = LA.precision(rows)
    assert p["live_events_scored"] == 90 and p["verdict"] == "inconclusive" and abs(p["precision"] - 40 / 90) < 1e-9
    p2 = LA.precision(rows + [{"kind": "live", "hit": 1, "forward_hit": 1}] * 10)
    assert p2["verdict"] == "supported" and p2["base_rate_single_bursts"] == 0


def test_hypotheses_keep_the_preregistered_rules_whatever_the_live_config():
    from lookedup_live import bursts as B
    mk = lambda lang, ts, qid: B.Burst(lang, "t", 1_791_000_000 + ts, "window", 5, 3, qid)
    pair = [mk("en", 0, "Q1"), mk("fr", 3600, "Q1")]                   # 60 min apart
    assert len(B.live_events(pair)) == 1                                 # live config: 120-min window
    with LA.prereg_rules() as w:
        assert w == 1800 and B.live_events(pair, w) == []                # pre-registered: 30 min
    assert B.GROUP_WINDOW_S == 7200                                      # restored


def test_h9_verdict_follows_the_preregistered_60_minutes(monkeypatch):
    monkeypatch.setattr(LA, "plot_leads", lambda leads, med: None)   # no figure from a unit test
    rows = [{"lead_minutes": m, "category": "death"} for m in ("-120", "-30", "", "90", "-60")]
    res = LA.h9_summary(rows)
    assert res["events"] == 5 and res["with_burst"] == 4
    assert res["median_lead_minutes"] == -45
    assert res["verdict"] == "rejected"
    assert res["share_lead_positive"] == 0.25
    early = LA.h9_summary([{"lead_minutes": "75", "category": None}] * 3)
    assert early["verdict"] == "supported"
    assert LA.h9_summary([{"lead_minutes": "", "category": None}])["verdict"] is None


class _R:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def test_revisions_follow_continuation(monkeypatch):
    pages = [{"query": {"pages": [{"revisions": [{"revid": 1}, {"revid": 2}]}]}, "continue": {"rvcontinue": "x"}},
             {"query": {"pages": [{"revisions": [{"revid": 3}]}]}}]
    calls = []

    class S:
        def get(self, url, params=None, timeout=None):
            calls.append(dict(params))
            return _R(pages.pop(0))

    monkeypatch.setattr(LA, "session", lambda: S())
    monkeypatch.setattr(LA.time, "sleep", lambda s: None)
    revs = LA.revisions("en", "Lionel_Messi", T0, T0 + timedelta(hours=1))
    assert [r["revid"] for r in revs] == [1, 2, 3]
    assert calls[0]["titles"] == "Lionel Messi" and calls[1]["rvcontinue"] == "x"


def test_revisions_give_up_after_retries(monkeypatch):
    class S:
        def get(self, *a, **k):
            raise ConnectionError("down")

    monkeypatch.setattr(LA, "session", lambda: S())
    monkeypatch.setattr(LA.time, "sleep", lambda s: None)
    assert LA.revisions("en", "X", T0, T0) == []


def test_daily_snapshot_writes_one_day(tmp_path, monkeypatch):
    import json
    from datetime import date

    from lookedup.store import LocalStore

    day = date(2026, 10, 11)
    lo = datetime(2026, 10, 11, tzinfo=UTC).timestamp()
    bursts = {"bursts": [{"ts": lo - 1, "title": "before"}, {"ts": lo, "title": "a"}, {"ts": lo + 86399, "title": "b"},
                         {"ts": lo + 86400, "title": "after"}]}
    stats = {"live_events_24h": 3}

    class S:
        def get(self, url, params=None, timeout=None):
            return _R(bursts if url.endswith("/bursts.json") else stats)

    monkeypatch.setattr(LA, "session", lambda: S())
    store = LocalStore(tmp_path)
    res = LA.snapshot(store, "https://live.example/", day)
    assert res == {"day": "2026-10-11", "bursts": 2, "live_events_24h": 3}
    lines = (tmp_path / "data/live/bursts/2026-10-11.jsonl").read_text().splitlines()
    assert [json.loads(l)["title"] for l in lines] == ["a", "b"]
    assert json.loads((tmp_path / "data/live/daily/2026-10-11-stats.json").read_text()) == stats


def test_append_scores_is_idempotent_per_day(tmp_path, monkeypatch):
    import csv
    from datetime import date

    from lookedup.store import LocalStore

    def row(day, kind="live", hit=1):
        r = dict.fromkeys(LA.FIELDS, "")
        return r | {"day": f"{day}", "kind": kind, "hit": str(hit), "forward_hit": str(hit)}

    store = LocalStore(tmp_path)
    d1, d2 = date(2026, 10, 9), date(2026, 10, 10)
    monkeypatch.setattr(LA, "score_day", lambda st, day: [row(day), row(day, "single", 0)])
    LA.append_scores(store, d1)
    LA.append_scores(store, d2)
    res = LA.append_scores(store, d2)                                  # the same day again
    rows = list(csv.DictReader((tmp_path / LA.LEAD_CSV).open()))
    assert sorted(r["day"] for r in rows) == ["2026-10-09", "2026-10-09", "2026-10-10", "2026-10-10"]
    assert res["live_events_scored"] == 2 and res["units_today"] == 2 and res["verdict"] == "inconclusive"


def test_score_day_without_bursts(tmp_path):
    from datetime import date

    from lookedup.store import LocalStore

    assert LA.score_day(LocalStore(tmp_path), date(2026, 10, 9)) == []


def test_score_day_hits_and_singles(tmp_path, monkeypatch):
    import json
    from datetime import date

    import lookedup.app_export as ax
    from lookedup.store import LocalStore

    day = date(2026, 10, 9)
    t = datetime(2026, 10, 9, 12, 10, tzinfo=UTC).timestamp()
    bursts = [{"lang": "en", "title": "X", "ts": t, "kind": "window", "edits_30m": 5, "editors_30m": 3, "qid": "Q1"},
              {"lang": "fr", "title": "X", "ts": t + 600, "kind": "window", "edits_30m": 5, "editors_30m": 3, "qid": "Q1"},
              {"lang": "de", "title": "Y", "ts": t, "kind": "window", "edits_30m": 6, "editors_30m": 4, "qid": "Q2"}]
    (tmp_path / "data/live/bursts").mkdir(parents=True)
    (tmp_path / "data/live/bursts/2026-10-09.jsonl").write_text("".join(json.dumps(b) + "\n" for b in bursts))
    monkeypatch.setattr(ax, "events_from_spikes", lambda con, files: ([{"qid": 1, "start_hour": datetime(2026, 10, 9, 14)}], []))
    rows = {r["qid"]: r for r in LA.score_day(LocalStore(tmp_path), day)}
    assert rows["Q1"]["kind"] == "live" and rows["Q1"]["hit"] == 1 and rows["Q1"]["forward_hit"] == 1
    assert rows["Q1"]["langs"] == "en fr" and rows["Q1"]["lead_minutes"] == 100     # dated at the fr burst, 12:20
    assert rows["Q2"]["kind"] == "single" and rows["Q2"]["hit"] == 0 and rows["Q2"]["event_start"] == ""


def test_run_h9_writes_rows(tmp_path, monkeypatch):
    import csv

    import duckdb

    import lookedup.warehouse as wh

    db_file = tmp_path / "w.duckdb"
    duckdb.connect(str(db_file)).close()
    monkeypatch.setattr(wh, "WAREHOUSE_DB", db_file)
    monkeypatch.setattr(LA, "OUT", tmp_path)
    monkeypatch.setattr(LA, "plot_leads", lambda leads, med: None)
    start = T0 + timedelta(hours=2)
    monkeypatch.setattr(LA, "h9_events", lambda con: [
        {"event_id": "E1", "qid": 1, "label_en": "X", "category": "death", "breadth": 5, "start_hour": start,
         "langs": [{"lang": "en", "title": "X", "lag": 0}]},
        {"event_id": "E2", "qid": 2, "label_en": "Y", "category": "sports", "breadth": 3, "start_hour": start,
         "langs": [{"lang": "fr", "title": "Y", "lag": 0}]}])
    monkeypatch.setattr(LA, "revisions", lambda lang, title, lo, hi:
                        [rev(m, f"u{m}") for m in range(0, 10, 2)] if lang == "en" else [])
    res = LA.run_h9()
    rows = list(csv.DictReader((tmp_path / "phase5_h9.csv").open()))
    assert [r["event_id"] for r in rows] == ["E1", "E2"]
    assert rows[0]["burst_lang"] == "en" and int(rows[0]["lead_minutes"]) > 0 and rows[1]["burst_at"] == ""
    assert res["events"] == 2 and res["with_burst"] == 1


def test_h9_events_window_order_and_languages():
    import duckdb

    from lookedup import live_analysis as LA

    con = duckdb.connect()
    con.execute("ATTACH ':memory:' AS wh")
    con.execute("""CREATE TABLE wh.main.fct_app_events AS SELECT * FROM (VALUES
        ('A', 1, TIMESTAMP '2026-09-15 10:00', 3, 900, 'fr', 'death', 'Alpha', 'multi_language'),
        ('B', 2, TIMESTAMP '2026-09-20 10:00', 4, 100, 'en', 'sports', 'Beta', 'multi_language'),
        ('C', 3, TIMESTAMP '2026-09-21 10:00', 9, 100, 'en', 'other', 'Gamma', 'single_language'),
        ('D', 4, TIMESTAMP '2026-10-10 00:00', 9, 100, 'en', 'other', 'Delta', 'multi_language'))
        t(event_id, qid, start_hour, breadth, excess_views, lead_lang, category, label_en, event_class)""")
    con.execute("""CREATE TABLE wh.main.fct_app_event_languages AS SELECT * FROM (VALUES
        ('A', 'en', 'Alpha_en', 1), ('A', 'fr', 'Alpha_fr', 0), ('A', 'de', NULL, 2), ('A', 'es', 'Alpha_es', 1),
        ('B', 'en', 'Beta', 0), ('C', 'en', 'Gamma', 0), ('D', 'en', 'Delta', 0))
        t(event_id, lang, title, spread_lag_hours)""")
    rows = LA.h9_events(con)
    assert [r["event_id"] for r in rows] == ["B", "A"]                 # widest first; single-language and out of window left out
    assert [l["lang"] for l in rows[1]["langs"]] == ["fr", "en", "es"]  # lead first, then by lag and code; no title, no row
    assert rows[1]["langs"][0] == {"lang": "fr", "title": "Alpha_fr", "lag": 0}


def test_burst_after_the_window_stops_the_search():
    revs = [rev(m, u) for m, u in [(0, "a"), (5, "b"), (10, "a"), (12, "c"), (14, "b"), (200, "d")]]
    assert LA.burst_time(revs, "en", "X", T0 - timedelta(hours=2), T0 - timedelta(hours=1)) == (None, None)


def test_append_scores_without_rows_commits_nothing(tmp_path, monkeypatch):
    from datetime import date

    import lookedup.scorer as sc
    from lookedup.store import LocalStore

    monkeypatch.setattr(LA, "score_day", lambda st, day: [])
    monkeypatch.setattr(sc, "_commit", lambda *a: (_ for _ in ()).throw(AssertionError("nothing to commit")))
    res = LA.append_scores(LocalStore(tmp_path), date(2026, 10, 9))
    assert res["units_today"] == 0 and res["day"] == "2026-10-09" and not (tmp_path / LA.LEAD_CSV).exists()


def test_anonymous_revision_counts():
    assert LA.counted({"timestamp": "2026-10-09T12:00:00Z", "user": None, "tags": [], "comment": "added a source"})


def test_rollback_tag_is_not_counted():
    assert not LA.counted(rev(0, "a", tags=["mw-rollback"])) and not LA.counted(rev(0, "a", tags=["mw-undo"]))


def test_precision_without_live_events():
    res = LA.precision([])
    assert res["verdict"] == "inconclusive" and res["live_events_scored"] == 0
