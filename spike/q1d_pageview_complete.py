"""Q1d: pageview_complete (daily per-project files) — lag, size, granularity.

Reads directory listings for the last ~2 weeks and streams only the first few MB of
yesterday's user file to inspect the line format (no full download).

Usage: .venv/bin/python spike/q1d_pageview_complete.py
"""

from __future__ import annotations

import bz2
import json
import re
from datetime import datetime, timedelta, timezone

from common import DERIVED, session

BASE = "https://dumps.wikimedia.org/other/pageview_complete"
ROW = re.compile(r'<a href="(pageviews-(\d{8})-(user|automated)\.bz2)">.*?</a>\s+(\d{2}-\w{3}-\d{4} \d{2}:\d{2})\s+(\d+)')


def listing(year: int, month: int) -> list[dict]:
    r = session.get(f"{BASE}/{year}/{year}-{month:02d}/", timeout=60)
    r.raise_for_status()
    out = []
    for name, day, kind, posted, size in ROW.findall(r.text):
        d = datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc)
        p = datetime.strptime(posted, "%d-%b-%Y %H:%M").replace(tzinfo=timezone.utc)
        out.append({"name": name, "day": d, "kind": kind, "posted": p, "bytes": int(size),
                    "url": f"{BASE}/{year}/{year}-{month:02d}/{name}",
                    "lag_h_after_day_end": round((p - d - timedelta(days=1)).total_seconds() / 3600, 1)})
    return out


def decode_hourly(s: str) -> dict[int, int]:
    """Hourly encoding: letter A..X = hour 0..23 followed by the count, e.g. 'A3C12'."""
    return {ord(h) - 65: int(c) for h, c in re.findall(r"([A-X])(\d+)", s)}


def main() -> None:
    now = datetime.now(timezone.utc)
    rows = listing(now.year, now.month)
    prev = now.replace(day=1) - timedelta(days=1)
    rows = listing(prev.year, prev.month) + rows
    user = [r for r in rows if r["kind"] == "user"][-14:]
    auto = [r for r in rows if r["kind"] == "automated"][-14:]
    res = {
        "user_days": len(user),
        "user_bz2_avg_gb": round(sum(r["bytes"] for r in user) / len(user) / 1e9, 3),
        "automated_bz2_avg_gb": round(sum(r["bytes"] for r in auto) / len(auto) / 1e9, 3),
        "lag_h_after_day_end": sorted(r["lag_h_after_day_end"] for r in user),
        "latest_user_file": user[-1]["name"],
        "latest_user_posted": user[-1]["posted"].isoformat(),
    }

    # Stream the first 8 MB of the latest user file and decompress what we can.
    r = session.get(user[-1]["url"], headers={"Range": "bytes=0-8388607"}, timeout=120)
    dec = bz2.BZ2Decompressor()
    text = dec.decompress(r.content).decode("utf-8", "replace")
    lines = text.split("\n")[:-1]
    res["sample_compressed_bytes"] = len(r.content)
    res["sample_uncompressed_bytes"] = len(text.encode())
    res["sample_lines"] = len(lines)
    res["sample_first_lines"] = lines[:5]
    parsed = []
    for ln in lines[:20000]:
        parts = ln.split(" ")
        if len(parts) == 6:
            proj, title, page_id, access, total, hourly = parts
            h = decode_hourly(hourly)
            parsed.append((proj, access, int(total), sum(h.values()) == int(total)))
    res["sample_parsed"] = len(parsed)
    res["sample_hourly_sums_match_total_pct"] = round(100 * sum(p[3] for p in parsed) / max(1, len(parsed)), 1)
    res["sample_access_types"] = sorted({p[1] for p in parsed})
    res["est_uncompressed_gb_per_day"] = round(
        res["sample_uncompressed_bytes"] / res["sample_compressed_bytes"] * user[-1]["bytes"] / 1e9, 1)

    (DERIVED / "q1d_pageview_complete.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
