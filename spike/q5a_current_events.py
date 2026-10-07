"""Q5a: fetch the last 60 daily Portal:Current_events pages and grep candidate events.

Usage: .venv/bin/python spike/q5a_current_events.py [keyword ...]
Daily wikitext goes to data/raw/events/; matching bullet lines are printed.
"""

from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timedelta, timezone

from common import RAW, session

KEYWORDS = sys.argv[1:] or ["dies", "died", "earthquake", "final", "wins", "assassinat", "crash",
                             "hurricane", "typhoon", "elected", "resign", "explosion", "killed"]


def main() -> None:
    out = RAW / "events"
    out.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date()
    for i in range(1, 61):
        day = today - timedelta(days=i)
        title = f"Portal:Current_events/{day.year}_{day:%B}_{day.day}"
        f = out / f"{day.isoformat()}.wiki"
        if not f.exists():
            r = session.get("https://en.wikipedia.org/w/index.php", params={"title": title, "action": "raw"}, timeout=30)
            f.write_text(r.text if r.ok else "")
            time.sleep(0.2)
        for line in f.read_text().splitlines():
            if line.startswith("*") and any(k.lower() in line.lower() for k in KEYWORDS):
                clean = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", line)
                clean = re.sub(r"\[https?://\S+ \(([^)]*)\)\]", r"(\1)", clean)
                print(day, clean[:220])


if __name__ == "__main__":
    main()
