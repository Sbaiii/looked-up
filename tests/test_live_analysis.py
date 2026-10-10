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
