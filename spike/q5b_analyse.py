"""Q5b: post-hoc detection analysis on the q5 hourly CSVs (no downloads).

Two detectors per (event, entity, language), first hour at or after event_hour - 6 h:
  * day-over-day  (spec): views >= 5 x same hour previous day, views >= 20
  * hour-over-hour:       views >= 3 x median(previous 3 hours in window), views >= 20
The second catches events whose previous day was already newsy (Harald V: palace said
"extremely serious" on 27 Aug, which inflated the day-over-day baseline).

Usage: .venv/bin/python spike/q5b_analyse.py
Writes docs/q5_detection_summary.csv.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from common import DERIVED, DOCS

FLOOR = 20
PUBLISH_LAG_H = 134 / 60  # median hourly-dump publication lag after the hour ends (Q1)


def parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def main() -> None:
    events = json.loads((DERIVED / "q5_events.json").read_text())
    out = []
    for ev in events:
        event_t = datetime.fromisoformat(ev["event_utc"])
        public_t = datetime.fromisoformat(ev["public_utc"])
        series = defaultdict(list)
        for r in csv.DictReader(open(DOCS / f"q5_{ev['key']}_hourly.csv")):
            series[(r["entity"], r["qid"], r["lang"], r["title"])].append(
                (parse(r["hour_start_utc"]), int(r["views"]), int(r["baseline_prev_day"])))
        start = event_t.replace(minute=0) - timedelta(hours=6)
        for (ent, qid, lang, title), s in series.items():
            s.sort()
            dod = next((h for h, v, b in s if h >= start and v >= FLOOR and v >= 5 * b), None)
            hoh = None
            for i in range(3, len(s)):
                h, v, _ = s[i]
                med = statistics.median(x[1] for x in s[i - 3:i])
                if h >= start and v >= FLOOR and v >= 3 * max(med, 1):
                    hoh = h
                    break

            def delay(h):
                return round((h - event_t).total_seconds() / 3600, 2) if h else None

            peak_h, peak_v = max(((h, v) for h, v, _ in s), key=lambda x: x[1])
            out.append({
                "event": ev["key"], "entity": ent, "qid": qid, "lang": lang, "title": title,
                "event_utc": f"{event_t:%Y-%m-%d %H:%M}", "public_utc": f"{public_t:%Y-%m-%d %H:%M}",
                "dod_first_spike_hour": f"{dod:%Y-%m-%d %H:00}" if dod else "",
                "dod_delay_h": delay(dod),
                "hoh_first_spike_hour": f"{hoh:%Y-%m-%d %H:00}" if hoh else "",
                "hoh_delay_h": delay(hoh),
                # detection hour h is complete at h+1, then the dump appears ~2.2 h later
                "hoh_visible_in_dumps_after_event_h": round(delay(hoh) + 1 + PUBLISH_LAG_H, 1) if hoh else None,
                "peak_hour": f"{peak_h:%Y-%m-%d %H:00}", "peak_views": peak_v,
                "views_in_event_hour": next((v for h, v, _ in s if h == event_t.replace(minute=0)), 0),
                "baseline_same_hour_prev_day": next((b for h, _, b in s if h == event_t.replace(minute=0)), 0),
            })
    with open(DOCS / "q5_detection_summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    for r in out:
        print(f"{r['event'][:20]:20} {r['entity'][:18]:18} {r['lang']:3} dod={r['dod_first_spike_hour'][5:]:12} "
              f"({r['dod_delay_h']}) hoh={r['hoh_first_spike_hour'][5:]:12} ({r['hoh_delay_h']}) peak={r['peak_views']}")


if __name__ == "__main__":
    main()
