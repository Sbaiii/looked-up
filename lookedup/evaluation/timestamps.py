"""Known event times for detection delays (prereg §5).

Order: an infobox ``timestamp`` field with a UTC date and time (e.g. Infobox earthquake),
else the creation time of the English article when it was created within ±2 days of the
portal date (new event articles). Otherwise None (the pair is skipped).
"""

from __future__ import annotations

import re
from datetime import date, datetime

from lookedup.dumps import session

_TS = re.compile(r"\|\s*timestamp\s*=\s*(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})")


def infobox_time(wikitext: str) -> datetime | None:
    m = _TS.search(wikitext)
    if not m:
        return None
    return datetime.fromisoformat(f"{m.group(1)}T{int(m.group(2)):02d}:{m.group(3)}")


def _api(params: dict) -> dict:
    r = session().get("https://en.wikipedia.org/w/api.php", params={**params, "format": "json", "formatversion": 2},
                      timeout=60)
    r.raise_for_status()
    return r.json()


def event_time(title: str, portal_date: date) -> dict | None:
    q = _api({"action": "query", "titles": title, "redirects": 1, "prop": "revisions", "rvprop": "content",
              "rvslots": "main"})
    pages = q.get("query", {}).get("pages", [])
    if not pages or "revisions" not in pages[0]:
        return None
    final_title = pages[0]["title"]
    text = pages[0]["revisions"][0]["slots"]["main"].get("content", "")
    t = infobox_time(text)
    if t and abs((t.date() - portal_date).days) <= 2:
        return {"time": t, "source": "infobox_timestamp"}
    first = _api({"action": "query", "titles": final_title, "prop": "revisions", "rvdir": "newer", "rvlimit": 1,
                  "rvprop": "timestamp"})
    p = first.get("query", {}).get("pages", [{}])[0]
    if "revisions" not in p:
        return None
    created = datetime.fromisoformat(p["revisions"][0]["timestamp"].replace("Z", ""))
    if abs((created.date() - portal_date).days) <= 2:
        return {"time": created, "source": "article_created"}
    return None
