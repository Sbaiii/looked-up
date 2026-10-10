"""The live engine: filters events, detects bursts, resolves QIDs, groups live events and renders the payloads
(/live.json, /stats.json). Holds 72 h of bursts; snapshots to disk without any user data."""

from __future__ import annotations

import gzip
import json
import threading
import time
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path

from lookedup_live.bursts import Burst, Detector, live_events
from lookedup_live.filters import language
from lookedup_live.qids import UI, Resolver
from lookedup_live.rules import RULES

SCHEMA_VERSION = 1
LIVE_WINDOW_S = RULES["live_window_minutes"] * 60
SINGLES_SHOWN = RULES["single_bursts_shown"]
HOURLY_KEEP = RULES["hourly_counts_hours"]


def iso(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def event_ts(event: dict) -> float:
    t = event.get("timestamp")
    if isinstance(t, (int, float)):
        return float(t)
    return datetime.fromisoformat(event["meta"]["dt"].replace("Z", "+00:00")).timestamp()


class Engine:
    def __init__(self, state_dir: Path | None = None) -> None:
        self.state_dir = state_dir
        self.detector = Detector()
        self.resolver = Resolver(state_dir / "qids.json" if state_dir else None)
        self.lock = threading.Lock()
        self.started_at = time.time()
        self.connected = False
        self.connected_since: float | None = None
        self.last_event_id: str | None = None
        self.last_event_at: float | None = None
        self.covered_since: float | None = None      # stream consumed continuously since this event time
        self.received: deque = deque()               # receipt times of all events (last 60 s)
        self.kept: deque = deque()
        self.langs_seen: dict[str, float] = {}
        self.live_seen: dict[str, str] = {}          # "qid|ts" -> hour key, to count live events per hour (a week)

    # ------------------------------------------------------------ ingest

    def handle(self, event: dict, event_id: str | None = None, now: float | None = None) -> Burst | None:
        now = now or time.time()
        with self.lock:
            self.received.append(now)
            if event_id:
                self.last_event_id = event_id
            lang = language(event)
            try:
                ts = event_ts(event)
            except (KeyError, ValueError, TypeError):
                return None
            self.last_event_at = max(self.last_event_at or 0, ts)
            if self.covered_since is None:
                self.covered_since = ts
            if lang is None:
                return None
            self.kept.append(now)
            self.langs_seen[lang] = ts
            b = self.detector.add(lang, event.get("title", ""), ts, event.get("user"), is_new=event.get("type") == "new")
            if b is not None:
                b.qid = self.resolver.get(lang, b.title)
                if b.qid is None:
                    self.resolver.want(lang, b.title)
            return b

    def attach_qids(self) -> None:
        with self.lock:
            for b in self.detector.bursts:
                if b.qid is None:
                    b.qid = self.resolver.get(b.lang, b.title)

    def mark_gap(self) -> None:
        """Called when the stream is lost without a resumable position: coverage restarts."""
        with self.lock:
            self.covered_since = None

    # ------------------------------------------------------------ payloads

    def _rate(self, q: deque, now: float) -> float:
        while q and q[0] < now - 60:
            q.popleft()
        return round(len(q) / 60, 2)

    def status(self, now: float | None = None) -> dict:
        now = now or time.time()
        window_lo = now - LIVE_WINDOW_S
        covered = self.covered_since or now
        gap = max(0.0, covered - window_lo) / 60
        if self.last_event_at and now - self.last_event_at > 120:      # stalled or asleep: the recent minutes are missing
            gap = max(gap, min(60.0, (now - self.last_event_at) / 60))
        return {"connected": self.connected, "started_at": iso(self.started_at), "connected_since": iso(self.connected_since),
                "last_event_at": iso(self.last_event_at), "events_per_s": self._rate(self.received, now),
                "kept_per_s": self._rate(self.kept, now),
                "languages_seen": sorted(l for l, t in self.langs_seen.items() if t > now - LIVE_WINDOW_S),
                "covered_since": iso(self.covered_since), "gap_minutes": round(gap)}

    def _label(self, qid: str, langs: list[str], titles: dict[str, str]) -> tuple[dict, dict]:
        item = self.resolver.items.get(qid, {})
        labels = {k: v for k, v in item.get("labels", {}).items() if k in UI or k in langs}
        for l, t in titles.items():
            labels.setdefault(l, t.replace("_", " "))
        return labels, {k: v[:80] for k, v in item.get("desc", {}).items() if k in UI}

    def live(self, now: float | None = None) -> dict:
        now = now or time.time()
        with self.lock:
            recent = [b for b in self.detector.bursts if b.ts > now - LIVE_WINDOW_S]
            events = []
            for ev in live_events(recent):
                langs = sorted(ev["languages"], key=lambda l: ev["languages"][l].ts)
                titles = {l: ev["languages"][l].title for l in langs}
                labels, desc = self._label(ev["qid"], langs, titles)
                events.append({
                    "qid": ev["qid"], "first_burst": iso(ev["first_burst"]), "live_since": iso(ev["ts"]),
                    "minutes_since_first_burst": round((now - ev["first_burst"]) / 60),
                    "breadth": len(langs), "labels": labels, "desc": desc,
                    "languages": [{"lang": l, "title": titles[l], "first_burst": iso(ev["languages"][l].ts),
                                   **self.detector.counts(l, titles[l], now)} for l in langs]})
            # ADR 0032: rank single-language bursts by distinct editors, then edits; show the top 5
            single = [b for b in recent if not any(b.qid == e["qid"] for e in events)]
            single.sort(key=lambda b: (-b.editors_30m, -b.edits_30m, -b.ts))
            singles = [{"lang": b.lang, "title": b.title, "qid": b.qid, "first_burst": iso(b.ts), "kind": b.kind,
                        "editors_at_burst": b.editors_30m, "edits_at_burst": b.edits_30m,
                        **self.detector.counts(b.lang, b.title, now)} for b in single[:SINGLES_SHOWN]]
            return {"schema_version": SCHEMA_VERSION, "generated_at": iso(now), "window_minutes": 60,
                    "status": self.status(now), "events": events, "single_language_bursts": singles}

    def _count_live(self, now: float) -> None:
        """Remember every live event once, by its hour, for a week (to judge the rules, ADR 0032)."""
        for e in live_events(list(self.detector.bursts)):
            self.live_seen.setdefault(f"{e['qid']}|{e['ts']}", iso(e["ts"] - e["ts"] % 3600)[:13])
        cutoff = iso(now - HOURLY_KEEP * 3600)[:13]
        self.live_seen = {k: h for k, h in self.live_seen.items() if h >= cutoff}

    def stats(self, now: float | None = None) -> dict:
        now = now or time.time()
        with self.lock:
            self._count_live(now)
            day = [b for b in self.detector.bursts if b.ts > now - 86400]
            per_hour = Counter(iso(b.ts - b.ts % 3600)[:13] for b in day)
            live_hour = Counter(h for h in self.live_seen.values() if h >= iso(now - 86400)[:13])
            return {"schema_version": SCHEMA_VERSION, "generated_at": iso(now), "status": self.status(now),
                    "bursts_per_hour": dict(sorted(per_hour.items())), "live_events_per_hour": dict(sorted(live_hour.items())),
                    "bursts_per_language": dict(Counter(b.lang for b in day).most_common()),
                    "bursts_24h": len(day), "live_events_24h": sum(live_hour.values()),
                    "live_events_per_hour_week": dict(sorted(Counter(self.live_seen.values()).items()))}

    def bursts_since(self, since: float) -> list[dict]:
        with self.lock:
            return [b.to_json() for b in self.detector.bursts if b.ts >= since]

    # ------------------------------------------------------------ snapshots (no user data)

    def snapshot(self, path: Path) -> None:
        with self.lock:
            now = time.time()
            ref = self.last_event_at or now               # stream time, so replays and restores agree
            arts = {f"{l}|{t}": {"edits": [ts for ts, _ in a.edits], "created_at": a.created_at, "last_burst": a.last_burst}
                    for (l, t), a in self.detector.articles.items() if a.edits and a.edits[-1][0] > ref - 3600}
            d = {"saved_at": now, "last_event_id": self.last_event_id, "last_event_at": self.last_event_at,
                 "covered_since": self.covered_since, "articles": arts,
                 "baselines": {l: list(m) for l, m in self.detector.baselines.medians.items()},
                 "bursts": [b.to_json() for b in self.detector.bursts], "live_seen": self.live_seen}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt") as f:
            json.dump(d, f)
        tmp.replace(path)
        self.resolver.save()

    def restore(self, path: Path) -> bool:
        if not path.exists():
            return False
        with gzip.open(path, "rt") as f:
            d = json.load(f)
        from lookedup_live.bursts import Article
        with self.lock:
            self.last_event_id = d.get("last_event_id")
            self.last_event_at = d.get("last_event_at")
            self.covered_since = d.get("covered_since") if self.last_event_id else None
            for key, a in d.get("articles", {}).items():
                l, t = key.split("|", 1)
                art = Article(created_at=a.get("created_at"), last_burst=a.get("last_burst"))
                art.edits.extend((ts, None) for ts in a["edits"])       # editors are never persisted
                self.detector.articles[(l, t)] = art
            for l, m in d.get("baselines", {}).items():
                self.detector.baselines.medians[l].extend(m)
            for b in d.get("bursts", []):
                self.detector.bursts.append(Burst(**b))
            self.live_seen.update(d.get("live_seen", {}))
        return True
