"""Sliding windows, per-wiki baselines, burst rules and cross-language grouping (docs/prereg_phase5.md).

Privacy: editors are counted through a salted hash that lives only inside the window it belongs to. Nothing
about users is ever written anywhere; snapshots keep edit timestamps only.
"""

from __future__ import annotations

import hashlib
import os
import statistics
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field

WINDOW_S = {"10m": 600, "30m": 1800, "60m": 3600}
BURST_EDITS = 5
BURST_EDITORS = 3
BURST_RATIO = 8.0
NEW_ARTICLE_EDITS = 5
NEW_ARTICLE_WINDOW_S = 3600
DEFAULT_BASELINE = 1.0           # median edits per edited article-hour before 24 h of own history (conservative)
BASELINE_HOURS = 7 * 24
MIN_BASELINE_HOURS = 24
COOLDOWN_S = 6 * 3600            # an article bursts at most once per 6 h
GROUP_WINDOW_S = 1800            # live event: same QID bursting in >= 2 languages within 30 min
KEEP_BURSTS_S = 72 * 3600

_SALT = os.urandom(16)


def editor_hash(user: str | None) -> str | None:
    if not user:
        return None
    return hashlib.blake2b(_SALT + user.encode(), digest_size=8).hexdigest()


@dataclass
class Article:
    edits: deque = field(default_factory=deque)          # (ts, editor_hash or None)
    created_at: float | None = None
    last_burst: float | None = None

    def trim(self, now: float) -> None:
        while self.edits and self.edits[0][0] <= now - WINDOW_S["60m"]:
            self.edits.popleft()

    def count(self, now: float, window: str) -> int:
        lo = now - WINDOW_S[window]
        return sum(1 for ts, _ in self.edits if ts > lo)

    def editors(self, now: float, window: str = "30m") -> int:
        lo = now - WINDOW_S[window]
        return len({h for ts, h in self.edits if ts > lo and h})


class Baselines:
    """Per wiki: median edits per edited article-hour, over the last 7 days of its own history."""

    def __init__(self) -> None:
        self.hour: int | None = None
        self.current: dict[str, Counter] = defaultdict(Counter)       # wiki -> title -> edits this hour
        self.medians: dict[str, deque] = defaultdict(lambda: deque(maxlen=BASELINE_HOURS))

    def add(self, lang: str, title: str, ts: float) -> None:
        h = int(ts // 3600)
        if self.hour is None:
            self.hour = h
        if h > self.hour:
            self.roll()
            self.hour = h
        self.current[lang][title] += 1

    def roll(self) -> None:
        for lang, counts in self.current.items():
            if counts:
                self.medians[lang].append(statistics.median(counts.values()))
        self.current = defaultdict(Counter)

    def get(self, lang: str) -> float:
        m = self.medians.get(lang)
        return statistics.median(m) if m and len(m) >= MIN_BASELINE_HOURS else DEFAULT_BASELINE


@dataclass
class Burst:
    lang: str
    title: str
    ts: float
    kind: str                       # "window" or "new"
    edits_30m: int
    editors_30m: int
    qid: str | None = None

    def to_json(self) -> dict:
        return {"lang": self.lang, "title": self.title, "ts": self.ts, "kind": self.kind,
                "edits_30m": self.edits_30m, "editors_30m": self.editors_30m, "qid": self.qid}


class Detector:
    def __init__(self) -> None:
        self.articles: dict[tuple[str, str], Article] = {}
        self.baselines = Baselines()
        self.bursts: deque[Burst] = deque()

    def add(self, lang: str, title: str, ts: float, user: str | None, is_new: bool = False) -> Burst | None:
        """Count one edit; return a Burst if this edit makes the article burst."""
        key = (lang, title)
        art = self.articles.get(key)
        if art is None:
            art = self.articles[key] = Article()
        art.trim(ts)
        art.edits.append((ts, editor_hash(user)))
        if is_new:
            art.created_at = ts
        self.baselines.add(lang, title, ts)
        if art.last_burst is not None and ts - art.last_burst < COOLDOWN_S:
            return None
        edits30, editors30 = art.count(ts, "30m"), art.editors(ts, "30m")
        kind = None
        if edits30 >= BURST_EDITS and editors30 >= BURST_EDITORS and 2 * edits30 >= BURST_RATIO * self.baselines.get(lang):
            kind = "window"
        elif art.created_at is not None and ts - art.created_at <= NEW_ARTICLE_WINDOW_S \
                and sum(1 for t, _ in art.edits if t >= art.created_at) >= NEW_ARTICLE_EDITS:
            kind = "new"
        if kind is None:
            return None
        art.last_burst = ts
        b = Burst(lang, title, ts, kind, edits30, editors30)
        self.bursts.append(b)
        return b

    def gc(self, now: float) -> None:
        """Drop idle articles and old bursts (bounded memory)."""
        for key in [k for k, a in self.articles.items()
                    if (not a.edits or a.edits[-1][0] <= now - WINDOW_S["60m"])
                    and (a.last_burst is None or now - a.last_burst > COOLDOWN_S)]:
            del self.articles[key]
        while self.bursts and self.bursts[0].ts < now - KEEP_BURSTS_S:
            self.bursts.popleft()

    def counts(self, lang: str, title: str, now: float) -> dict:
        a = self.articles.get((lang, title))
        if not a:
            return {"edits_10m": 0, "edits_30m": 0, "edits_60m": 0, "editors_30m": 0}
        return {"edits_10m": a.count(now, "10m"), "edits_30m": a.count(now, "30m"), "edits_60m": a.count(now, "60m"),
                "editors_30m": a.editors(now, "30m")}


def live_events(bursts: list[Burst], window_s: int = GROUP_WINDOW_S) -> list[dict]:
    """Group bursts by QID: a live event is a QID bursting in >= 2 languages within 30 minutes.

    Returns one dict per live event: qid, ts (the second language's burst), first_burst, languages {lang: burst}."""
    by_qid: dict[str, list[Burst]] = defaultdict(list)
    for b in bursts:
        if b.qid:
            by_qid[b.qid].append(b)
    out = []
    for qid, bs in by_qid.items():
        bs.sort(key=lambda b: b.ts)
        first_by_lang: dict[str, Burst] = {}
        for b in bs:
            first_by_lang.setdefault(b.lang, b)
        firsts = sorted(first_by_lang.values(), key=lambda b: b.ts)
        for i in range(1, len(firsts)):
            if firsts[i].ts - firsts[i - 1].ts <= window_s:
                out.append({"qid": qid, "ts": firsts[i].ts, "first_burst": firsts[0].ts,
                            "languages": {b.lang: b for b in firsts}})
                break
    return sorted(out, key=lambda e: -e["ts"])
