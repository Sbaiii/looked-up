from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "live"))   # the live service is its own package

from lookedup_live import bursts as B  # noqa: E402
from lookedup_live.engine import Engine
from lookedup_live.filters import LANGUAGES, is_maintenance, language

T0 = 1_791_000_000.0
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "recentchange_60s.jsonl"


def ev(wiki="enwiki", title="X", ts=T0, user="a", type_="edit", ns=0, bot=False, comment=""):
    return {"wiki": wiki, "title": title, "timestamp": ts, "user": user, "type": type_, "namespace": ns, "bot": bot,
            "comment": comment}


def test_languages_match_the_ingested_set():
    from lookedup.languages import active_codes
    assert LANGUAGES == active_codes()


def test_filters():
    assert language(ev()) == "en" and language(ev(wiki="zh_yuewiki")) is None
    assert language(ev(ns=1)) is None and language(ev(bot=True)) is None
    assert language(ev(type_="categorize")) is None and language(ev(type_="new")) == "en"
    for c in ("Reverted edits by X", "Undid revision 123", "rv vandalism", "fix typo", "[[WP:HotCat]] added",
              "using AWB", "{{Orphan}}"):
        assert is_maintenance(c), c
    assert not is_maintenance("Added death date and source") and language(ev(comment="update")) == "en"


def test_sliding_windows_and_distinct_editors_without_storing_users():
    d = B.Detector()
    for i, (dt, u) in enumerate([(0, "a"), (300, "b"), (900, "a"), (2000, "c")]):
        d.add("en", "X", T0 + dt, u)
    c = d.counts("en", "X", T0 + 2000)
    assert c == {"edits_10m": 1, "edits_30m": 3, "edits_60m": 4, "editors_30m": 3}
    stored = d.articles[("en", "X")].edits
    assert all(h is None or (len(h) == 16 and h not in "abc") for _, h in stored)     # salted hashes, never names


def test_burst_rule_needs_five_edits_three_editors_in_30_minutes():
    d = B.Detector()
    users = ["a", "a", "b", "b", "b"]
    out = [d.add("en", "X", T0 + 60 * i, u) for i, u in enumerate(users)]
    assert out == [None] * 5                                    # 5 edits but only 2 editors
    b = d.add("en", "X", T0 + 360, "c")
    assert b and b.kind == "window" and b.edits_30m == 6 and b.editors_30m == 3
    assert d.add("en", "X", T0 + 400, "d") is None              # cooldown: one burst per article per 6 h
    d2 = B.Detector()
    assert all(d2.add("en", "Y", T0 + 600 * i, u) is None for i, u in enumerate("abcdef"))   # spread over 50 min


def test_baseline_raises_the_bar_on_a_busy_wiki():
    d = B.Detector()
    d.baselines.medians["en"].extend([4.0] * 30)                # 24 h+ of history: median 4 edits/article-hour
    assert d.baselines.get("en") == 4.0 and d.baselines.get("fr") == B.DEFAULT_BASELINE
    out = [d.add("en", "X", T0 + 60 * i, u) for i, u in enumerate("abcdefghijklmnop")]
    assert next(i for i, b in enumerate(out) if b) == 15         # needs 2 x edits >= 8 x 4 -> 16 edits


def test_new_article_rule():
    d = B.Detector()
    d.add("fr", "Nouveau", T0, "a", is_new=True)
    out = [d.add("fr", "Nouveau", T0 + 600 * i, "a") for i in range(1, 5)]
    assert out[-1] is not None and out[-1].kind == "new"


def test_qid_grouping_needs_two_languages_within_30_minutes():
    mk = lambda lang, ts, qid: B.Burst(lang, "t", T0 + ts, "window", 5, 3, qid)
    events = B.live_events([mk("en", 0, "Q1"), mk("fr", 1700, "Q1"), mk("de", 0, "Q2"), mk("es", 2000, "Q2"),
                            mk("ja", 0, "Q3"), mk("ja", 100, "Q3"), mk("it", 0, None)])
    assert [e["qid"] for e in events] == ["Q1"]
    assert events[0]["ts"] == T0 + 1700 and set(events[0]["languages"]) == {"en", "fr"}


def test_engine_payload_reports_gaps_and_live_events():
    e = Engine()
    for lang, wiki in (("en", "enwiki"), ("fr", "frwiki")):
        for i, u in enumerate("abcde"):
            e.handle(ev(wiki=wiki, title="Comet", ts=T0 + 3000 + 60 * i, user=u), now=T0 + 3600)
    e.resolver.qids |= {"en|Comet": "Q42", "fr|Comet": "Q42"}
    e.resolver.items["Q42"] = {"labels": {"en": "Comet X"}, "desc": {"en": "a comet"}}
    e.attach_qids()
    live = e.live(now=T0 + 3600)
    assert live["status"]["gap_minutes"] == 50                   # coverage began 10 min before "now"
    [event] = live["events"]
    assert event["qid"] == "Q42" and event["breadth"] == 2 and event["labels"]["en"] == "Comet X"
    assert event["languages"][0]["edits_30m"] == 5
    asleep = e.live(now=T0 + 3600 + 3 * 3600)                     # nothing received for 3 h: say so
    assert asleep["status"]["gap_minutes"] == 60 and asleep["events"] == []


def test_snapshot_round_trip_keeps_no_user_data(tmp_path):
    e = Engine()
    for i, u in enumerate("abcde"):
        e.handle(ev(title="Z", ts=T0 + 60 * i, user=u), event_id='[{"offset": 1}]', now=T0 + 300)
    e.snapshot(tmp_path / "s.json.gz")
    raw = gzip.open(tmp_path / "s.json.gz", "rt").read()
    assert '"a"' not in raw and "user" not in raw
    e2 = Engine()
    assert e2.restore(tmp_path / "s.json.gz") and e2.last_event_id == '[{"offset": 1}]'
    assert e2.detector.counts("en", "Z", T0 + 300)["edits_30m"] == 5


def test_replay_the_60_second_sample():
    e = Engine()
    rows = [json.loads(l) for l in FIXTURE.open()]
    for r in rows:
        e.handle(r, now=r["timestamp"])
    s = e.status(now=rows[-1]["timestamp"])
    assert len(rows) > 100
    assert 10 <= len(s["languages_seen"]) <= 30
    kept = sum(1 for r in rows if language(r))
    assert 0 < kept < len(rows)                                   # filters drop bots, other namespaces, maintenance
    live = e.live(now=rows[-1]["timestamp"])
    assert live["schema_version"] == 1 and isinstance(live["events"], list)
