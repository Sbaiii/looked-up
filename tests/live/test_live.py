from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from typing import ClassVar

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
    for dt, u in [(0, "a"), (300, "b"), (900, "a"), (2000, "c")]:
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


def test_new_article_rule_needs_two_editors():
    d = B.Detector()
    d.add("fr", "Solo", T0, "a", is_new=True)
    assert all(d.add("fr", "Solo", T0 + 600 * i, "a") is None for i in range(1, 6))   # one author: not attention
    d.add("fr", "Nouveau", T0, "a", is_new=True)
    out = [d.add("fr", "Nouveau", T0 + 600 * i, u) for i, u in enumerate("abab", start=1)]
    assert out[-1] is not None and out[-1].kind == "new"


def test_qid_grouping_needs_two_languages_within_120_minutes():
    mk = lambda lang, ts, qid: B.Burst(lang, "t", T0 + ts, "window", 5, 3, qid)
    events = B.live_events([mk("en", 0, "Q1"), mk("fr", 1700, "Q1"), mk("de", 0, "Q2"), mk("es", 7000, "Q2"),
                            mk("ja", 0, "Q3"), mk("ja", 100, "Q3"), mk("it", 0, None), mk("pt", 0, "Q4"), mk("pl", 7300, "Q4")])
    assert sorted(e["qid"] for e in events) == ["Q1", "Q2"]                 # Q4: 2 h 2 min apart, Q3: one language
    q1 = next(e for e in events if e["qid"] == "Q1")
    assert q1["ts"] == T0 + 1700 and set(q1["languages"]) == {"en", "fr"}


def test_single_bursts_rank_by_editors_then_edits_and_live_events_are_counted_hourly():
    e = Engine()
    now = T0 + 3600
    e.detector.bursts.extend([B.Burst("en", "A", now - 600, "window", 9, 3), B.Burst("fr", "B", now - 500, "window", 5, 5),
                              B.Burst("de", "C", now - 400, "window", 6, 3)])
    assert [b["title"] for b in e.live(now=now)["single_language_bursts"]] == ["B", "A", "C"]
    e.detector.bursts.extend([B.Burst("en", "X", now - 300, "window", 5, 3, "Q9"), B.Burst("es", "X", now - 200, "window", 5, 3, "Q9")])
    st = e.stats(now=now)
    assert st["live_events_24h"] == 1 and sum(st["live_events_per_hour_week"].values()) == 1


def test_engine_payload_reports_gaps_and_live_events():
    e = Engine()
    for _lang, wiki in (("en", "enwiki"), ("fr", "frwiki")):
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
    with gzip.open(tmp_path / "s.json.gz", "rt") as f:
        raw = f.read()
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


def test_editor_hash_is_stable_per_user_and_none_for_anonymous():
    assert B.editor_hash(None) is None and B.editor_hash("") is None
    assert B.editor_hash("Alice") == B.editor_hash("Alice")
    assert B.editor_hash("Alice") != B.editor_hash("Bob")
    assert "Alice" not in B.editor_hash("Alice")


def test_article_window_keeps_one_hour():
    a = B.Article()
    for m in (0, 20, 50, 70):
        a.edits.append((T0 + m * 60, B.editor_hash(f"u{m}")))
    a.trim(T0 + 70 * 60)
    assert [round((ts - T0) / 60) for ts, _ in a.edits] == [20, 50, 70]
    assert a.count(T0 + 70 * 60, "30m") == 2 and a.count(T0 + 70 * 60, "10m") == 1
    assert a.editors(T0 + 70 * 60, "60m") == 3


def test_baseline_is_the_default_until_enough_hours():
    b = B.Baselines()
    for h in range(B.MIN_BASELINE_HOURS - 1):
        b.add("en", "X", T0 + h * 3600)
    b.add("en", "X", T0 + (B.MIN_BASELINE_HOURS - 1) * 3600)          # closes hour MIN - 1
    assert b.get("en") == B.DEFAULT_BASELINE
    assert b.get("fr") == B.DEFAULT_BASELINE


def test_baseline_uses_the_wiki_median_once_it_has_enough_hours():
    b = B.Baselines()
    for h in range(B.MIN_BASELINE_HOURS + 1):
        for _ in range(4):
            b.add("en", "X", T0 + h * 3600)                            # 4 edits on one article every hour
    assert b.get("en") == 4


def test_no_second_burst_during_the_cooldown():
    d = B.Detector()
    first = [d.add("en", "X", T0 + i * 60, f"u{i}") for i in range(6)]
    assert any(first)
    again = [d.add("en", "X", T0 + 600 + i * 60, f"v{i}") for i in range(6)]
    assert not any(again)


def test_gc_drops_idle_articles_and_old_bursts():
    d = B.Detector()
    d.add("en", "Quiet", T0, "a")
    d.bursts.append(B.Burst("en", "Old", T0, "window", 5, 3))
    later = T0 + B.KEEP_BURSTS_S + 3600
    d.gc(later)
    assert ("en", "Quiet") not in d.articles
    assert not d.bursts


def test_counts_of_an_unknown_article_are_zero():
    assert B.Detector().counts("en", "Nothing", T0) == {"edits_10m": 0, "edits_30m": 0, "edits_60m": 0, "editors_30m": 0}


def test_burst_json_has_no_user_fields():
    j = B.Burst("fr", "Y", T0, "new", 5, 2, qid="Q1").to_json()
    assert j == {"lang": "fr", "title": "Y", "ts": T0, "kind": "new", "edits_30m": 5, "editors_30m": 2, "qid": "Q1"}


def test_engine_time_helpers():
    from lookedup_live.engine import event_ts, iso
    assert iso(None) is None
    assert iso(0) == "1970-01-01T00:00:00Z"
    assert event_ts({"timestamp": 12}) == 12.0
    assert event_ts({"meta": {"dt": "1970-01-01T00:01:00Z"}}) == 60.0


def test_events_without_a_timestamp_are_ignored():
    e = Engine()
    bad = ev()
    del bad["timestamp"]
    assert e.handle(bad, now=T0) is None
    assert e.last_event_at is None and not e.detector.articles


def test_a_stalled_feed_reports_a_gap():
    e = Engine()
    e.handle(ev(ts=T0), now=T0)
    assert e.status(now=T0 + 60)["gap_minutes"] == 59          # just started: the rest of the hour is not covered yet
    assert e.status(now=T0 + 30 * 60)["gap_minutes"] == 30     # no event for 30 minutes


def test_bursts_since_filters_by_time():
    e = Engine()
    e.detector.bursts.extend([B.Burst("en", "A", T0, "window", 5, 3), B.Burst("en", "B", T0 + 600, "window", 5, 3)])
    assert [b["title"] for b in e.bursts_since(T0 + 1)] == ["B"]
    assert len(e.bursts_since(T0)) == 2


def test_revert_summaries_are_maintenance():
    for c in ("Reverted edits by X", "Undid revision 123", "rv vandalism", "rollback"):
        assert is_maintenance(c), c
    for c in (None, "", "Added death date", "riverside"):
        assert not is_maintenance(c), c


def test_resolver_queue_and_cache_round_trip(tmp_path):
    from lookedup_live.qids import Resolver
    r = Resolver(tmp_path / "qids.json")
    r.qids["en|Known"] = "Q1"
    r.want("en", "Known")
    r.want("en", "New")
    assert r.pending == {("en", "New")}
    assert r.get("en", "Known") == "Q1" and r.get("en", "New") is None
    r.save()
    assert Resolver(tmp_path / "qids.json").get("en", "Known") == "Q1"


class _WD:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class _Ok:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def test_resolver_stores_qids_labels_and_descriptions(monkeypatch):
    from lookedup_live import qids
    monkeypatch.setattr(qids.time, "sleep", lambda s: None)
    r = qids.Resolver()
    r.session = _WD([_Ok({"entities": {
        "Q597": {"sitelinks": {"frwiki": {"title": "Lisbonne"}}, "labels": {"en": {"value": "Lisbon"}},
                 "descriptions": {"en": {"value": "capital of Portugal"}}},
        "-1": {"missing": ""}}})])
    r.want("fr", "Lisbonne")
    r.want("fr", "Nulle_part")
    assert r.resolve_pending() == 2
    assert r.get("fr", "Lisbonne") == "Q597" and r.get("fr", "Nulle_part") is None and "fr|Nulle_part" in r.qids
    assert r.items["Q597"] == {"labels": {"en": "Lisbon"}, "desc": {"en": "capital of Portugal"}}
    assert r.session.calls[0]["sites"] == "frwiki" and r.session.calls[0]["languages"] == "en|fr|es"


def test_resolver_requeues_after_a_failure(monkeypatch):
    import requests
    from lookedup_live import qids
    r = qids.Resolver()
    r.session = _WD([requests.ConnectionError("down")])
    r.want("de", "Berlin")
    assert r.resolve_pending() == 0
    assert r.pending == {("de", "Berlin")} and "de|Berlin" not in r.qids


def test_resolver_batches_per_wiki(monkeypatch):
    from lookedup_live import qids
    monkeypatch.setattr(qids.time, "sleep", lambda s: None)
    r = qids.Resolver()
    r.session = _WD([_Ok({"entities": {}})] * 3)
    for i in range(60):
        r.want("en", f"T{i}")
    r.want("ja", "東京")
    assert r.resolve_pending() == 61
    assert sorted((c["sites"], c["titles"].count("|") + 1) for c in r.session.calls) == [("enwiki", 10), ("enwiki", 50), ("jawiki", 1)]


def _service(monkeypatch, tmp_path):
    import importlib

    import pytest
    pytest.importorskip("fastapi")                     # the Space dependencies are not installed in CI
    monkeypatch.setenv("LIVE_STATE_DIR", str(tmp_path))
    from lookedup_live import app
    return importlib.reload(app)


def test_service_cache_window(monkeypatch, tmp_path):
    svc = _service(monkeypatch, tmp_path)
    clock = [T0]
    monkeypatch.setattr(svc.time, "time", lambda: clock[0])
    builds = []
    build = lambda: builds.append(1) or {"n": len(builds)}
    assert json.loads(svc.cached("x", build).body) == {"n": 1}
    clock[0] += svc.CACHE_S - 1
    assert json.loads(svc.cached("x", build).body) == {"n": 1}
    clock[0] += 2
    r = svc.cached("x", build)
    assert json.loads(r.body) == {"n": 2} and r.headers["cache-control"] == f"public, max-age={svc.CACHE_S}"


def test_health_endpoint(monkeypatch, tmp_path):
    svc = _service(monkeypatch, tmp_path)
    svc.engine.connected = True
    h = svc.health()
    assert set(h) == {"ok", "connected", "last_event_at", "gap_minutes"} and h["ok"] and h["connected"]


def test_bursts_endpoint_caps_the_window(monkeypatch, tmp_path):
    svc = _service(monkeypatch, tmp_path)
    monkeypatch.setattr(svc.time, "time", lambda: T0)
    seen = []
    monkeypatch.setattr(svc.engine, "bursts_since", lambda since: seen.append(since) or [])
    svc._cache.clear()
    svc.bursts(hours=500)
    svc.bursts(hours=2)
    assert seen == [T0 - 72 * 3600, T0 - 2 * 3600]


def test_service_lifespan_order(monkeypatch, tmp_path):
    import asyncio
    svc = _service(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(svc, "start", lambda: calls.append("start"))
    monkeypatch.setattr(svc, "shutdown", lambda: calls.append("shutdown"))

    async def run():
        async with svc.lifespan(svc.app):
            calls.append("serving")

    asyncio.run(run())
    assert calls == ["start", "serving", "shutdown"]


def test_mark_gap_restarts_coverage():
    e = Engine()
    e.handle(ev(ts=T0), now=T0)
    assert e.covered_since == T0
    e.mark_gap()
    assert e.covered_since is None
    e.handle(ev(ts=T0 + 600), now=T0 + 600)
    assert e.covered_since == T0 + 600


def test_restore_without_a_snapshot(tmp_path):
    e = Engine()
    assert e.restore(tmp_path / "missing.json.gz") is False
    assert not e.detector.articles and e.last_event_id is None


def test_corrupt_qid_cache_is_ignored(tmp_path):
    from lookedup_live.qids import Resolver
    bad = tmp_path / "qids.json"
    bad.write_text("{not json")
    r = Resolver(bad)
    assert r.qids == {} and r.items == {}


def test_parse_sse_messages():
    from lookedup_live.stream import parse_sse
    lines = [":ok", "id: [1]", "data: {\"a\":", "data: 1}", "", "event: message", "data: {}", "", "", "id: x"]
    assert list(parse_sse(iter(lines))) == [("[1]", '{"a":\n1}'), (None, "{}")]


class _Stream:
    def __init__(self, lines, status=200):
        self.lines, self.status = lines, status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            import requests
            raise requests.HTTPError(str(self.status))

    def iter_lines(self, decode_unicode=True):
        return iter(self.lines)


def test_cold_start_replays_and_handles_events(monkeypatch):
    import threading

    from lookedup_live import stream
    stop, calls = threading.Event(), []
    e = Engine()
    payload = json.dumps(ev(ts=T0))

    class S:
        headers: ClassVar[dict] = {}

        def get(self, url, headers=None, params=None, stream=None, timeout=None):
            calls.append((dict(headers), dict(params)))
            stop.set()                                             # one connection only
            return _Stream(["id: [7]", f"data: {payload}", ""])

    monkeypatch.setattr(stream.requests, "Session", S)
    e.covered_since = T0 - 99
    stream.consume(e, stop)
    assert "since" in calls[0][1] and "Last-Event-ID" not in calls[0][0]
    assert e.covered_since is None                                   # the gap is marked before replaying
    assert e.last_event_id is None and not e.detector.articles      # stop is checked before each message


def test_resumed_stream_handles_events(monkeypatch):
    import threading

    from lookedup_live import stream
    stop, calls = threading.Event(), []
    e = Engine()
    e.last_event_id = "[6]"
    lines = [f"id: [{7 + i}]\ndata: {json.dumps(ev(ts=T0 + i, user=str(i)))}".split("\n") + [""] for i in range(3)]
    flat = [l for msg in lines for l in msg] + ["data: not json", ""]

    class S:
        headers: ClassVar[dict] = {}

        def get(self, url, headers=None, params=None, stream=None, timeout=None):
            calls.append((dict(headers), dict(params)))
            return _Stream(flat)

    monkeypatch.setattr(stream.requests, "Session", S)
    monkeypatch.setattr(stop, "wait", lambda t: True)                # stop after the first connection ends
    stream.consume(e, stop)
    assert calls == [({"Last-Event-ID": "[6]"}, {})]
    assert e.last_event_id == "[9]" and e.detector.articles[("en", "X")].count(T0 + 3, "10m") == 3
    assert e.connected is False


def test_stream_error_backs_off(monkeypatch):
    import threading

    import requests
    from lookedup_live import stream
    e, waits = Engine(), []
    stop = threading.Event()

    class S:
        headers: ClassVar[dict] = {}

        def get(self, *a, **k):
            raise requests.ConnectionError("down")

    def wait(t):
        waits.append(t)
        return len(waits) >= 4

    monkeypatch.setattr(stream.requests, "Session", S)
    monkeypatch.setattr(stop, "wait", wait)
    stream.consume(e, stop, max_backoff=4)
    assert waits == [1.0, 2.0, 4, 4]


def test_resolver_loop_round(monkeypatch):
    import threading

    from lookedup_live import stream
    e = Engine()
    e.detector.bursts.append(B.Burst("en", "X", T0, "window", 5, 3))
    rounds = iter([False, True])
    stop = threading.Event()
    monkeypatch.setattr(stop, "wait", lambda t: next(rounds))
    monkeypatch.setattr(e.resolver, "resolve_pending", lambda: e.resolver.qids.update({"en|X": "Q42"}) or 1)
    gc = []
    monkeypatch.setattr(e.detector, "gc", lambda now: gc.append(now))
    stream.resolver_loop(e, stop)
    assert e.detector.bursts[0].qid == "Q42" and len(gc) == 1


def test_shift_fetches_state_or_cold_starts(tmp_path, monkeypatch):
    import huggingface_hub
    from lookedup_live import shift
    src = tmp_path / "hub"
    src.mkdir()
    (src / "state.json.gz").write_bytes(b"state")
    (src / "qids.json").write_bytes(b"{}")
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda repo, path, **k: str(src / path.rsplit("/", 1)[1]))
    out = tmp_path / "state"
    out.mkdir()
    assert shift.fetch_state(out) is True and (out / "state.json.gz").read_bytes() == b"state"

    def missing(*a, **k):
        raise FileNotFoundError("no state yet")

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", missing)
    assert shift.fetch_state(tmp_path) is False


def test_shift_publish_commits_payloads_and_bursts(tmp_path, monkeypatch):
    from lookedup_live import shift
    commits = []

    class Api:
        def create_commit(self, repo, repo_type=None, operations=None, commit_message=None):
            commits.append(([op.path_in_repo for op in operations], commit_message))

    monkeypatch.setattr(shift, "_api", lambda: Api())
    now = 1_791_000_000.0 + 900                                      # mid half-hour: no state handover this round
    monkeypatch.setattr(shift.time, "time", lambda: now)
    e = Engine(tmp_path)
    e.detector.bursts.append(B.Burst("en", "X", now - 60, "window", 5, 3))
    shift.publish(e, tmp_path)
    paths, message = commits[0]
    assert {"data/live/live.json", "data/live/stats.json"} <= set(paths)
    assert sum(p.startswith("data/live/bursts/") for p in paths) == 2
    assert "data/live/state.json.gz" not in paths and message.startswith("data: live layer")


def test_shift_final_publish_includes_state(tmp_path, monkeypatch):
    from lookedup_live import shift
    commits = []

    class Api:
        def create_commit(self, repo, repo_type=None, operations=None, commit_message=None):
            commits.append([op.path_in_repo for op in operations])

    monkeypatch.setattr(shift, "_api", lambda: Api())
    monkeypatch.setattr(shift.time, "time", lambda: 1_791_000_000.0 + 900)
    shift.publish(Engine(tmp_path), tmp_path, final=True)
    assert {"data/live/state.json.gz", "data/live/qids.json"} <= set(commits[0])
    assert (tmp_path / "state.json.gz").exists()


def test_service_start_and_shutdown(monkeypatch, tmp_path):
    svc = _service(monkeypatch, tmp_path)
    started, snaps = [], []

    class FakeThread:
        def __init__(self, target, daemon):
            self.target, self.daemon = target, daemon

        def start(self):
            started.append(self.daemon)

    monkeypatch.setattr(svc.threading, "Thread", FakeThread)
    monkeypatch.setattr(svc.engine, "restore", lambda path: snaps.append(("restore", path.name)) or False)
    monkeypatch.setattr(svc.engine, "snapshot", lambda path: snaps.append(("snapshot", path.name)))
    svc.start()
    assert started == [True, True, True] and snaps == [("restore", "state.json.gz")]
    svc.shutdown()
    assert svc.stop.is_set() and snaps[-1] == ("snapshot", "state.json.gz")


def test_shift_main_without_publishing(tmp_path, monkeypatch):
    import sys

    from lookedup_live import shift
    calls = []
    monkeypatch.setattr(sys, "argv", ["shift", "--hours", "0", "--state-dir", str(tmp_path), "--no-publish"])
    monkeypatch.setattr(shift, "consume", lambda engine, stop: calls.append("consume"))
    monkeypatch.setattr(shift, "resolver_loop", lambda engine, stop: calls.append("resolve"))
    monkeypatch.setattr(shift, "fetch_state", lambda d: pytest_fail_if_called())
    monkeypatch.setattr(shift, "publish", lambda *a, **k: pytest_fail_if_called())
    shift.main()
    assert (tmp_path / "state.json.gz").exists()                     # the background fakes may not have run yet


def pytest_fail_if_called():
    raise AssertionError("must not be called with --no-publish")


def test_restore_brings_back_baselines_and_bursts(tmp_path):
    e = Engine()
    e.detector.baselines.medians["en"].extend([2.0, 3.0])
    e.detector.bursts.append(B.Burst("en", "X", T0, "window", 5, 3, qid="Q1"))
    e.last_event_id = "[9]"
    e.snapshot(tmp_path / "s.json.gz")
    back = Engine()
    assert back.restore(tmp_path / "s.json.gz") is True
    assert list(back.detector.baselines.medians["en"]) == [2.0, 3.0]
    assert back.detector.bursts[0].qid == "Q1" and back.last_event_id == "[9]"


def test_rules_location(monkeypatch, tmp_path):
    import pytest
    from lookedup_live import rules
    custom = tmp_path / "live.yml"
    custom.write_text("x: 1\n")
    monkeypatch.setenv("LIVE_CONFIG", str(custom))
    assert rules._find() == custom
    monkeypatch.setenv("LIVE_CONFIG", str(tmp_path / "missing.yml"))
    assert rules._find().name == "live.yml" and rules._find() != custom        # falls back to the repo's config
    monkeypatch.setattr(rules, "__file__", str(tmp_path / "pkg" / "lookedup_live" / "rules.py"))
    with pytest.raises(FileNotFoundError, match="LIVE_CONFIG"):
        rules._find()


def test_live_and_stats_endpoints(monkeypatch, tmp_path):
    svc = _service(monkeypatch, tmp_path)
    svc._cache.clear()
    live = json.loads(svc.live().body)
    stats = json.loads(svc.stats().body)
    assert live["schema_version"] == 1 and "events" in live and "single_language_bursts" in live
    assert "bursts_per_hour" in stats and "live_events_per_hour_week" in stats
    assert svc.live().headers["cache-control"] == f"public, max-age={svc.CACHE_S}"


def test_shift_main_resumes_publishes_and_hands_over(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    from lookedup_live import shift
    prev = Engine()
    prev.last_event_id = "[42]"
    prev.snapshot(tmp_path / "state.json.gz")
    clock = [1_791_000_000.0]
    monkeypatch.setattr(shift, "time", SimpleNamespace(time=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s)))
    monkeypatch.setattr(sys, "argv", ["shift", "--hours", "0.5", "--every", "600", "--state-dir", str(tmp_path)])
    monkeypatch.setattr(shift, "consume", lambda engine, stop: None)
    monkeypatch.setattr(shift, "resolver_loop", lambda engine, stop: None)
    monkeypatch.setattr(shift, "fetch_state", lambda d: True)
    calls = []

    def publish(engine, state_dir, final=False):
        calls.append((final, engine.last_event_id))
        if len(calls) == 1:
            raise RuntimeError("Hub timeout")

    monkeypatch.setattr(shift, "publish", publish)
    shift.main()
    assert calls == [(False, "[42]"), (False, "[42]"), (False, "[42]"), (True, "[42]")]   # 3 rounds of 10 min, then final


def test_service_snapshot_loop(monkeypatch, tmp_path):
    svc = _service(monkeypatch, tmp_path)
    waits, snaps = [], []

    class Stop:
        def wait(self, s):
            waits.append(s)
            return len(waits) > 2                     # two rounds, then shutdown

    monkeypatch.setattr(svc, "stop", Stop())
    monkeypatch.setattr(svc.engine, "snapshot", lambda path: snaps.append(path))
    svc._snapshots()
    assert waits == [300, 300, 300] and snaps == [tmp_path / "state.json.gz"] * 2


def test_burst_on_a_known_title_is_not_queued():
    e = Engine()
    e.resolver.qids["en|Comet"] = "Q42"
    bursts = [e.handle(ev(title="Comet", ts=T0 + 60 * i, user=u), now=T0 + 600) for i, u in enumerate("abcde")]
    b = next(x for x in bursts if x is not None)
    assert b.qid == "Q42" and e.resolver.pending == set()


def test_attach_qids_keeps_existing_qids():
    e = Engine()
    e.detector.bursts.extend([B.Burst("en", "A", T0, "window", 5, 3, qid="Q1"), B.Burst("en", "B", T0, "window", 5, 3)])
    e.resolver.qids |= {"en|A": "Q999", "en|B": "Q2"}
    e.attach_qids()
    assert [b.qid for b in e.detector.bursts] == ["Q1", "Q2"]


def test_resolver_item_without_the_sitelink(monkeypatch):
    from lookedup_live import qids
    monkeypatch.setattr(qids.time, "sleep", lambda s: None)
    r = qids.Resolver()
    r.session = _WD([_Ok({"entities": {"Q5": {"sitelinks": {"enwiki": {"title": "Human"}}, "labels": {}, "descriptions": {}}}})])
    r.want("fr", "Humain")
    assert r.resolve_pending() == 1
    assert r.get("fr", "Humain") is None and "fr|Humain" in r.qids and r.items["Q5"] == {"labels": {}, "desc": {}}


def test_resolver_loop_without_new_qids(monkeypatch):
    import threading

    from lookedup_live import stream
    e = Engine()
    rounds = iter([False, True])
    stop = threading.Event()
    monkeypatch.setattr(stop, "wait", lambda t: next(rounds))
    monkeypatch.setattr(e.resolver, "resolve_pending", lambda: 0)
    monkeypatch.setattr(e, "attach_qids", lambda: pytest_fail_if_called())
    monkeypatch.setattr(e.detector, "gc", lambda now: None)
    stream.resolver_loop(e, stop)


def test_consume_returns_at_once_when_stopped(monkeypatch):
    import threading

    import requests
    from lookedup_live import stream
    stop = threading.Event()
    stop.set()
    monkeypatch.setattr(requests.Session, "get", lambda *a, **k: pytest_fail_if_called())
    stream.consume(Engine(), stop)


def test_shift_api_uses_the_token(monkeypatch):
    import huggingface_hub
    from lookedup_live import shift
    made = []
    monkeypatch.setattr(huggingface_hub, "HfApi", lambda token=None: made.append(token) or "api")
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    assert shift._api() == "api" and made == ["hf_test"]


def test_baseline_roll_skips_an_empty_wiki():
    b = B.Baselines()
    b.current["en"]["A"] += 3
    b.current["fr"]                                                 # touched but empty
    b.roll()
    assert list(b.medians["en"]) == [3] and "fr" not in b.medians


def test_live_payload_drops_bursts_outside_the_window():
    from lookedup_live.engine import LIVE_WINDOW_S
    e = Engine()
    now = T0 + 10 * 3600
    e.detector.bursts.extend([B.Burst("en", "Old", now - LIVE_WINDOW_S - 60, "window", 9, 9),
                              B.Burst("en", "New", now - 60, "window", 5, 3)])
    assert [b["title"] for b in e.live(now=now)["single_language_bursts"]] == ["New"]


def test_live_event_language_order_and_no_double_listing():
    e = Engine()
    now = T0 + 3600
    e.detector.bursts.extend([B.Burst("fr", "X", now - 500, "window", 5, 3, "Q9"), B.Burst("en", "X", now - 900, "window", 5, 3, "Q9"),
                              B.Burst("de", "Y", now - 100, "window", 5, 3, "Q8")])
    live = e.live(now=now)
    [ev] = live["events"]
    assert [l["lang"] for l in ev["languages"]] == ["en", "fr"] and ev["breadth"] == 2 and ev["minutes_since_first_burst"] == 15
    assert [b["title"] for b in live["single_language_bursts"]] == ["Y"]


def test_single_bursts_are_capped():
    from lookedup_live.engine import SINGLES_SHOWN
    e = Engine()
    now = T0 + 3600
    e.detector.bursts.extend(B.Burst("en", f"T{i}", now - 60 * i, "window", 5, 3) for i in range(1, SINGLES_SHOWN + 4))
    assert len(e.live(now=now)["single_language_bursts"]) == SINGLES_SHOWN


def test_stats_per_hour_and_language():
    e = Engine()
    now = T0 + 5 * 3600
    e.detector.bursts.extend([B.Burst("en", "A", now - 25 * 3600, "window", 5, 3),            # older than a day
                              B.Burst("en", "B", now - 3600, "window", 5, 3), B.Burst("fr", "C", now - 3500, "window", 5, 3),
                              B.Burst("en", "D", now - 60, "window", 5, 3)])
    st = e.stats(now=now)
    assert st["bursts_24h"] == 3 and st["bursts_per_language"] == {"en": 2, "fr": 1}
    assert sum(st["bursts_per_hour"].values()) == 3 and list(st["bursts_per_hour"]) == sorted(st["bursts_per_hour"])


def test_burst_again_after_the_cooldown():
    d = B.Detector()
    first = [d.add("en", "X", T0 + 60 * i, u) for i, u in enumerate("abcde")]
    assert first[-1] is not None
    later = T0 + B.COOLDOWN_S + 600
    again = [d.add("en", "X", later + 60 * i, u) for i, u in enumerate("fghij")]
    assert again[-1] is not None and again[-1].ts == later + 240


def test_anonymous_edits_are_not_editors():
    d = B.Detector()
    out = [d.add("en", "X", T0 + 60 * i, u) for i, u in enumerate([None, None, None, "a", "b"])]
    assert out == [None] * 5                                         # 5 edits, 2 editors
    assert d.counts("en", "X", T0 + 300) == {"edits_10m": 5, "edits_30m": 5, "edits_60m": 5, "editors_30m": 2}


def test_new_article_rule_expires():
    d = B.Detector()
    d.add("fr", "Tard", T0, "a", is_new=True)
    late = [d.add("fr", "Tard", T0 + B.NEW_ARTICLE_WINDOW_S + 600 * i, u) for i, u in enumerate("abab", start=1)]
    assert late == [None] * 4                                        # too late for the new-article rule, too slow for the window


def test_baseline_needs_a_day_of_history():
    b = B.Baselines()
    b.medians["en"].extend([6.0] * 23)
    assert b.get("en") == B.DEFAULT_BASELINE
    b.medians["en"].append(6.0)
    assert b.get("en") == 6.0


def test_editor_hash_is_stable_and_distinct():
    assert B.editor_hash("alice") == B.editor_hash("alice") != B.editor_hash("bob")
    assert B.editor_hash(None) is None and B.editor_hash("") is None


def test_language_rejects_sister_projects():
    assert language(ev(wiki="enwiktionary")) is None
    assert language(ev(wiki="commonswiki")) is None
    assert language(ev(wiki="frwiki")) == "fr"


def test_counts_of_an_unseen_article():
    assert B.Detector().counts("en", "Nothing", T0) == {"edits_10m": 0, "edits_30m": 0, "edits_60m": 0, "editors_30m": 0}


def test_burst_json_fields():
    d = B.Burst("en", "X", T0, "window", 5, 3, qid="Q1").to_json()
    assert d == {"lang": "en", "title": "X", "ts": T0, "kind": "window", "edits_30m": 5, "editors_30m": 3, "qid": "Q1"}


def test_resolver_without_cache_file():
    from lookedup_live.qids import Resolver
    r = Resolver()
    assert r.qids == {} and r.items == {} and r.pending == set()
    r.save()                                                        # no file configured: a no-op


def test_new_engine_status():
    s = Engine().status(now=T0)
    assert s["connected"] is False and s["last_event_at"] is None


def test_parse_sse_ignores_comments():
    from lookedup_live.stream import parse_sse
    assert list(parse_sse([": keep-alive", "", ": another"])) == []


def test_parse_sse_multiline_data():
    from lookedup_live.stream import parse_sse
    [(i, d)] = list(parse_sse(["id: [5]", "data: {\"a\":", "data: 1}", ""]))
    assert i == "[5]" and json.loads(d) == {"a": 1}


def test_same_title_two_wikis():
    d = B.Detector()
    for lang in ("en", "fr"):
        out = [d.add(lang, "X", T0 + 60 * i, u) for i, u in enumerate("abcde")]
        assert out[-1] is not None
    assert [b.lang for b in d.bursts] == ["en", "fr"]


def test_live_events_need_qids():
    mk = lambda lang, qid: B.Burst(lang, "t", T0, "window", 5, 3, qid)
    assert B.live_events([mk("en", None), mk("fr", None)]) == []
