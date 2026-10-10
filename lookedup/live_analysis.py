"""Phase 5 analyses (docs/prereg_phase5.md).

H9: lead time of edit bursts over the first spiking hour, reconstructed from MediaWiki revision histories with
    the live layer's own rules (lookedup_live.bursts), for the 30 days ending 9 Oct.
H10: precision of live multi-language edit bursts for reading events, scored daily against the lake and
    appended to data/live/lead_time.csv on the Hub (pipelines never commit to the repo).

    python -m lookedup.cli live-h9          # backtest -> docs/analysis/phase5_h9.csv, phase5_metrics.json, figure
    python -m lookedup.cli live-score       # daily: score the live bursts of two days ago
"""

from __future__ import annotations

import csv
import json
import logging
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from lookedup import db
from lookedup.dumps import session
from lookedup.settings import ROOT

sys.path.insert(0, str(ROOT / "live"))          # the live layer's rules are the single definition of a burst
from lookedup_live.bursts import Burst, Detector, live_events  # noqa: E402
from lookedup_live.filters import REVERT_TAGS, is_maintenance  # noqa: E402

log = logging.getLogger(__name__)

OUT = ROOT / "docs" / "analysis"
FIG = ROOT / "docs" / "figures"
H9_FROM, H9_TO = datetime(2026, 9, 10), datetime(2026, 10, 10)
H9_CAP = 2000
OTHER_LANGS = 4


# ---------------------------------------------------------------- revisions

def revisions(lang: str, title: str, start: datetime, end: datetime) -> list[dict]:
    """Revisions of one article in [start, end] (oldest first): timestamp, user, tags, comment, parentid."""
    api = f"https://{lang}.wikipedia.org/w/api.php"
    params = {"action": "query", "prop": "revisions", "titles": title.replace("_", " "), "rvlimit": "max",
              "rvprop": "timestamp|user|tags|comment|ids", "rvdir": "newer",
              "rvstart": f"{start:%Y-%m-%dT%H:%M:%SZ}", "rvend": f"{end:%Y-%m-%dT%H:%M:%SZ}",
              "format": "json", "formatversion": 2, "redirects": 1}
    out: list[dict] = []
    while True:
        for attempt in range(4):
            try:
                r = session().get(api, params=params, timeout=30)
                r.raise_for_status()
                d = r.json()
                break
            except Exception as e:  # noqa: BLE001 (network)
                if attempt == 3:
                    log.warning("revisions %s:%s failed: %s", lang, title, e)
                    return out
                time.sleep(2 * (attempt + 1))
        for page in d.get("query", {}).get("pages", []):
            out += page.get("revisions", [])
        if "continue" not in d:
            return out
        params |= d["continue"]
        time.sleep(0.05)


def counted(rev: dict) -> bool:
    """The pre-registered filter for API revisions: no bot accounts, no revert tags, no maintenance comments."""
    user = rev.get("user") or ""
    return not user.lower().endswith("bot") and not (set(rev.get("tags", [])) & REVERT_TAGS) \
        and not is_maintenance(rev.get("comment"))


def burst_time(revs: list[dict], lang: str, title: str, lo: datetime, hi: datetime) -> tuple[float | None, str | None]:
    """First burst (live rules, default baseline) with time in [lo, hi]; returns (epoch seconds, kind)."""
    det = Detector()
    lo_s, hi_s = lo.replace(tzinfo=timezone.utc).timestamp(), hi.replace(tzinfo=timezone.utc).timestamp()
    for r in revs:
        if not counted(r):
            continue
        ts = datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")).timestamp()
        b = det.add(lang, title, ts, r.get("user"), is_new=r.get("parentid") == 0)
        if b is not None and lo_s <= b.ts <= hi_s:
            return b.ts, b.kind
        if b is not None and b.ts > hi_s:
            break
    return None, None


# ---------------------------------------------------------------- H9

def h9_events(con) -> list[dict]:
    rows = con.sql(f"""
        SELECT e.event_id, e.qid, e.start_hour, e.breadth, e.excess_views, e.lead_lang, e.category, e.label_en,
               list(struct_pack(lang := l.lang, title := l.title, lag := l.spread_lag_hours)
                    ORDER BY (l.lang = e.lead_lang) DESC, l.spread_lag_hours, l.lang) AS langs
        FROM wh.main.fct_app_events e JOIN wh.main.fct_app_event_languages l USING (event_id)
        WHERE e.event_class = 'multi_language' AND e.start_hour >= TIMESTAMP '{H9_FROM}'
          AND e.start_hour < TIMESTAMP '{H9_TO}' AND l.title IS NOT NULL
        GROUP BY ALL ORDER BY e.breadth DESC, e.excess_views DESC LIMIT {H9_CAP}""")
    cols = rows.columns
    return [dict(zip(cols, r)) for r in rows.fetchall()]


def run_h9() -> dict:
    from lookedup.warehouse import WAREHOUSE_DB

    con = db.connect()
    con.execute(f"ATTACH '{WAREHOUSE_DB}' AS wh (READ_ONLY)")
    events = h9_events(con)
    log.info("H9: %d events", len(events))
    rows = []
    for i, e in enumerate(events):
        start = e["start_hour"]
        best = (None, None, None)
        for L in e["langs"][: 1 + OTHER_LANGS]:
            revs = revisions(L["lang"], L["title"], start - timedelta(hours=48), start + timedelta(hours=24))
            ts, kind = burst_time(revs, L["lang"], L["title"], start - timedelta(hours=24), start + timedelta(hours=24))
            if ts is not None and (best[0] is None or ts < best[0]):
                best = (ts, L["lang"], kind)
        start_s = start.replace(tzinfo=timezone.utc).timestamp()
        rows.append({"event_id": e["event_id"], "qid": e["qid"], "label": e["label_en"], "category": e["category"],
                     "breadth": e["breadth"], "start_hour": f"{start:%Y-%m-%dT%H}:00Z",
                     "burst_at": datetime.fromtimestamp(best[0], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if best[0] else "",
                     "burst_lang": best[1] or "", "burst_kind": best[2] or "",
                     "lead_minutes": round((start_s - best[0]) / 60) if best[0] else ""})
        if i % 100 == 0:
            log.info("H9 %d/%d", i, len(events))
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "phase5_h9.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return h9_summary(rows)


def h9_summary(rows: list[dict]) -> dict:
    leads = [int(r["lead_minutes"]) for r in rows if r["lead_minutes"] != ""]
    q = statistics.quantiles(leads, n=4) if len(leads) >= 4 else [None, None, None]
    by_cat: dict[str, list[int]] = {}
    for r in rows:
        if r["lead_minutes"] != "":
            by_cat.setdefault(r["category"] or "other", []).append(int(r["lead_minutes"]))
    med = statistics.median(leads) if leads else None
    res = {"events": len(rows), "with_burst": len(leads), "share_with_burst": len(leads) / len(rows) if rows else 0,
           "median_lead_minutes": med, "p25": q[0], "p75": q[2],
           "share_lead_positive": sum(1 for x in leads if x > 0) / len(leads) if leads else None,
           "by_category": {k: {"n": len(v), "median": statistics.median(v)} for k, v in sorted(by_cat.items()) if len(v) >= 10},
           "verdict": None if med is None else ("supported" if med >= 60 else "rejected")}
    plot_leads(leads, med)
    return res


def plot_leads(leads: list[int], med: float | None) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from lookedup.evaluation.figures import ACCENT, INK, _style

    if not leads:
        return
    clip = [max(-24 * 60, min(24 * 60, x)) / 60 for x in leads]
    fig, ax = plt.subplots(figsize=(7, 3.8))
    ax.hist(clip, bins=range(-24, 25), color=ACCENT, edgecolor="white")
    ax.axvline(0, color=INK, lw=1)
    ax.axvline(1, color=INK, lw=1, ls=":")
    ax.set_xlabel("first spiking hour minus edit burst (hours; > 0: editors first)", color=INK)
    ax.set_ylabel("events", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.84))
    _style(ax, f"Edit bursts vs the first reading spike (median {med / 60:+.1f} h)",
           f"{len(leads)} multi-language events, 10 Sep – 9 Oct; dotted line: the pre-registered 60 min")
    ax.grid(axis="x", visible=False)
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / "phase5_lead_time.png", dpi=160)
    plt.close(fig)


# ---------------------------------------------------------------- H10 (daily accumulation on the lake)

LEAD_CSV = "data/live/lead_time.csv"
FIELDS = ["day", "qid", "kind", "burst_at", "langs", "hit", "forward_hit", "event_start", "lead_minutes", "scored_at"]


def score_day(store, day: date) -> list[dict]:
    """Score the live layer's bursts of ``day`` against the lake's reading events (needs day + 2 published)."""
    import tempfile

    from lookedup.app_export import events_from_spikes
    from lookedup.scorer import spikes_path

    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        f = store.fetch(f"data/live/bursts/{day:%Y-%m-%d}.jsonl", tmp)
        if not f:
            return []
        bursts = [Burst(**json.loads(l)) for l in f.read_text().splitlines() if l.strip()]
        spike_files = [p for p in (store.fetch(spikes_path(day + timedelta(days=k)), tmp / "s") for k in (-1, 0, 1, 2)) if p]
        events, _ = events_from_spikes(db.connect(), spike_files)
    starts: dict[str, list[datetime]] = {}
    for e in events:                    # every product event spans >= 2 languages (ADR 0021)
        starts.setdefault(f"Q{e['qid']}", []).append(e["start_hour"])
    lives = live_events(bursts)
    live_qids = {e["qid"] for e in lives}
    units = [("live", e["qid"], e["ts"], sorted(e["languages"])) for e in lives]
    units += [("single", b.qid, b.ts, [b.lang]) for b in bursts if b.qid and b.qid not in live_qids]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for kind, qid, ts, langs in units:
        b = datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None)
        floor = b.replace(minute=0, second=0, microsecond=0)
        cand = [s for s in starts.get(qid, []) if floor - timedelta(hours=2) <= s <= floor + timedelta(hours=24)]
        first = min(cand) if cand else None
        rows.append({"day": f"{day}", "qid": qid, "kind": kind, "burst_at": f"{b:%Y-%m-%dT%H:%M:%S}Z",
                     "langs": " ".join(langs), "hit": int(bool(cand)), "forward_hit": int(any(s >= floor for s in cand)),
                     "event_start": f"{first:%Y-%m-%dT%H}:00Z" if first else "",
                     "lead_minutes": round((first - b).total_seconds() / 60) if first else "",  # > 0: editors first
                     "scored_at": now})
    return rows


def append_scores(store, day: date) -> dict:
    """Append ``day``'s scored rows to data/live/lead_time.csv on the lake (idempotent per day)."""
    import io
    import tempfile

    from lookedup.scorer import _commit

    rows = score_day(store, day)
    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        old = store.fetch(LEAD_CSV, tmp / "old")
        existing = list(csv.DictReader(io.StringIO(old.read_text()))) if old else []
        existing = [r for r in existing if r["day"] != f"{day}"] + rows
        out = tmp / "lead_time.csv"
        with out.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(existing)
        if rows:
            _commit(store, {LEAD_CSV: out}, f"data: score live bursts of {day} ({len(rows)} units)")
    return precision(existing) | {"day": f"{day}", "units_today": len(rows)}


def precision(rows: list[dict]) -> dict:
    live = [r for r in rows if r["kind"] == "live"]
    single = [r for r in rows if r["kind"] == "single"]
    p = lambda rs, k="hit": (sum(int(r[k]) for r in rs) / len(rs)) if rs else None
    n = len(live)
    return {"live_events_scored": n, "precision": p(live), "forward_precision": p(live, "forward_hit"),
            "base_rate_single_bursts": p(single), "single_bursts_scored": len(single),
            "verdict": ("inconclusive" if n < 100 else ("supported" if p(live) >= 0.30 else "rejected"))}
