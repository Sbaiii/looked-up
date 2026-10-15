from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
    assert kind == "window" and ts == (T0 + timedelta(minutes=14)).replace(tzinfo=timezone.utc).timestamp()
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
    lo = datetime(2026, 10, 11, tzinfo=timezone.utc).timestamp()
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
        r = {f: "" for f in LA.FIELDS}
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
