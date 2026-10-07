"""Shared helpers for the Phase 0 feasibility spike."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

UA = "looked-up/0.1 (https://github.com/Sbaiii/looked-up; abdellahsbaisbai@gmail.com)"
HEADERS = {"User-Agent": UA}

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DERIVED = ROOT / "data" / "derived"
DOCS = ROOT / "docs"

DUMPS = "https://dumps.wikimedia.org/other/pageviews"

session = requests.Session()
session.headers.update(HEADERS)

LISTING_RE = re.compile(
    r'<a href="(pageviews-(\d{8})-(\d{2})0000\.gz)">.*?</a>\s+(\d{2}-\w{3}-\d{4} \d{2}:\d{2})\s+(\d+)'
)


def list_hourly(year: int, month: int) -> list[dict]:
    """Parse the monthly directory listing of hourly pageview dumps."""
    url = f"{DUMPS}/{year}/{year}-{month:02d}/"
    r = session.get(url, timeout=60)
    r.raise_for_status()
    out = []
    for name, day, hour, posted, size in LISTING_RE.findall(r.text):
        out.append(
            {
                "name": name,
                "url": url + name,
                "hour": datetime.strptime(day + hour, "%Y%m%d%H").replace(tzinfo=timezone.utc),
                "posted": datetime.strptime(posted, "%d-%b-%Y %H:%M").replace(tzinfo=timezone.utc),
                "gz_bytes": int(size),
            }
        )
    return out


def hourly_url(dt: datetime) -> str:
    return f"{DUMPS}/{dt:%Y}/{dt:%Y-%m}/pageviews-{dt:%Y%m%d-%H}0000.gz"


def download(url: str, dest: Path, retries: int = 8) -> tuple[Path, float]:
    """Download url to dest, resuming a partial .part file with HTTP Range.

    Skips the download if dest already exists. Returns (path, seconds). Long transfers
    from dumps.wikimedia.org get cut (observed at exactly 256 MiB), hence the resume.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest, 0.0
    tmp = dest.with_suffix(dest.suffix + ".part")
    t0 = time.perf_counter()
    for attempt in range(retries):
        have = tmp.stat().st_size if tmp.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with session.get(url, stream=True, timeout=120, headers=headers) as r:
                if r.status_code == 416:  # already complete
                    break
                r.raise_for_status()
                total = have + int(r.headers.get("Content-Length", 0))
                mode = "ab" if have and r.status_code == 206 else "wb"
                with open(tmp, mode) as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            if tmp.stat().st_size >= total:
                break
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(min(30, 5 * (attempt + 1)))
    else:
        raise RuntimeError(f"incomplete download after {retries} attempts: {url}")
    tmp.rename(dest)
    return dest, time.perf_counter() - t0


def human(n: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
