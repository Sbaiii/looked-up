"""Q5c: how fast do *editors* react? (the edit-stream lead over pageview dumps)

For each Q5 event and language: first revision of the article at/after the event time
(for new articles: the page creation), from the MediaWiki revisions API. This is what the
live edit stream would have shown us, minutes after the event.

Usage: .venv/bin/python spike/q5c_edit_lead.py
Writes docs/q5_edit_lead.csv.
"""

from __future__ import annotations

import csv
import json
import time
from datetime import datetime, timezone

from common import DERIVED, DOCS, session


def first_rev_after(lang: str, title: str, after: datetime) -> dict | None:
    r = session.get(f"https://{lang}.wikipedia.org/w/api.php", params={
        "action": "query", "prop": "revisions", "titles": title, "rvlimit": 1, "rvdir": "newer",
        "rvstart": after.strftime("%Y-%m-%dT%H:%M:%SZ"), "rvprop": "timestamp|user|comment|size",
        "redirects": 1, "format": "json", "formatversion": 2}, timeout=30).json()
    time.sleep(0.2)
    pages = r.get("query", {}).get("pages", [])
    if not pages or "revisions" not in pages[0]:
        return None
    rev = pages[0]["revisions"][0]
    return {"ts": datetime.fromisoformat(rev["timestamp"].replace("Z", "+00:00")),
            "user": rev.get("user", ""), "comment": rev.get("comment", "")[:120]}


def creation(lang: str, title: str) -> datetime | None:
    r = session.get(f"https://{lang}.wikipedia.org/w/api.php", params={
        "action": "query", "prop": "revisions", "titles": title, "rvlimit": 1, "rvdir": "newer",
        "rvprop": "timestamp", "redirects": 1, "format": "json", "formatversion": 2}, timeout=30).json()
    time.sleep(0.2)
    pages = r.get("query", {}).get("pages", [])
    if not pages or "revisions" not in pages[0]:
        return None
    return datetime.fromisoformat(pages[0]["revisions"][0]["timestamp"].replace("Z", "+00:00"))


def main() -> None:
    events = {e["key"]: e for e in json.loads((DERIVED / "q5_events.json").read_text())}
    summary = list(csv.DictReader(open(DOCS / "q5_detection_summary.csv")))
    out = []
    for s in summary:
        ev = events[s["event"]]
        event_t = datetime.fromisoformat(ev["event_utc"])
        created = creation(s["lang"], s["title"])
        rev = first_rev_after(s["lang"], s["title"], event_t)
        new_article = created is not None and created >= event_t
        first = created if new_article else (rev["ts"] if rev else None)
        out.append({
            "event": s["event"], "entity": s["entity"], "lang": s["lang"], "title": s["title"],
            "event_utc": s["event_utc"], "new_article": int(new_article),
            "first_edit_after_event_utc": f"{first:%Y-%m-%d %H:%M}" if first else "",
            "edit_lead_min": round((first - event_t).total_seconds() / 60) if first else "",
            "first_edit_comment": "" if new_article else (rev or {}).get("comment", ""),
            "pageview_visible_after_event_h": s["hoh_visible_in_dumps_after_event_h"],
        })
        print(out[-1]["event"][:12], out[-1]["entity"][:16], out[-1]["lang"], out[-1]["first_edit_after_event_utc"],
              out[-1]["edit_lead_min"], "NEW" if new_article else "", out[-1]["first_edit_comment"][:60])
    with open(DOCS / "q5_edit_lead.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)


if __name__ == "__main__":
    main()
