"""Wikimedia dump access: directory listings, publication lag, resumable downloads.

Hourly files are named after the END of the hour they cover
(``pageviews-20261007-100000.gz`` holds 09:00-10:00 UTC), see ADR 0008.
"""

from __future__ import annotations

import logging
import re
import socket
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from lookedup.settings import DUMPS_BASE, PVC_BASE, REST_BASE, USER_AGENT

log = logging.getLogger(__name__)

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})

_LISTING_RE = re.compile(
    r'<a href="(pageviews-(\d{8})-(\d{2})0000\.gz)">.*?</a>\s+(\d{2}-\w{3}-\d{4} \d{2}:\d{2})\s+(\d+)'
)


def session() -> requests.Session:
    """Shared HTTP session that always sends the project User-Agent."""
    return _session


@dataclass(frozen=True)
class HourlyFile:
    """One hourly dump file as seen in the server directory listing."""

    name: str
    url: str
    ts_hour_start: datetime  # naive UTC
    posted: datetime  # naive UTC, directory listing timestamp
    size: int

    @property
    def lag_minutes(self) -> int:
        """Minutes between the end of the covered hour and publication."""
        return int((self.posted - self.ts_hour_start - timedelta(hours=1)).total_seconds() // 60)


def file_name(ts_hour_start: datetime) -> str:
    """Dump filename for the hour starting at ``ts_hour_start`` (name = end of hour)."""
    end = ts_hour_start + timedelta(hours=1)
    return f"pageviews-{end:%Y%m%d-%H}0000.gz"


def file_url(ts_hour_start: datetime) -> str:
    end = ts_hour_start + timedelta(hours=1)
    return f"{DUMPS_BASE}/{end:%Y}/{end:%Y-%m}/{file_name(ts_hour_start)}"


def hour_start_from_name(name: str) -> datetime:
    """``pageviews-20261007-100000.gz`` -> 2026-10-07 09:00 (naive UTC)."""
    m = re.search(r"pageviews-(\d{8})-(\d{2})0000", name)
    if not m:
        raise ValueError(f"not an hourly dump name: {name}")
    end = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H")
    return end - timedelta(hours=1)


def list_month(year: int, month: int) -> list[HourlyFile]:
    """Parse the monthly directory listing. A missing month (404) yields []."""
    url = f"{DUMPS_BASE}/{year}/{year}-{month:02d}/"
    r = _session.get(url, timeout=60)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    out = []
    for name, _day, _hour, posted, size in _LISTING_RE.findall(r.text):
        out.append(HourlyFile(
            name=name,
            url=url + name,
            ts_hour_start=hour_start_from_name(name),
            posted=datetime.strptime(posted, "%d-%b-%Y %H:%M"),
            size=int(size),
        ))
    return out


def available_hours(start: datetime, end: datetime) -> dict[datetime, HourlyFile]:
    """Hourly files published on the server for hour starts in [start, end)."""
    months = sorted({(d.year, d.month) for d in (start, end, end + timedelta(hours=1))})
    found: dict[datetime, HourlyFile] = {}
    for y, m in months:
        for f in list_month(y, m):
            if start <= f.ts_hour_start < end:
                found[f.ts_hour_start] = f
    return found


def pvc_url(day: date) -> str:
    """URL of the pageview_complete user file for one UTC day."""
    return f"{PVC_BASE}/{day:%Y}/{day:%Y-%m}/pageviews-{day:%Y%m%d}-user.bz2"


class _Stalled(Exception):
    """Raised when a transfer stalls or trickles; the download resumes on a new connection."""


class _Watchdog(threading.Thread):
    """Shut down a connection whose throughput stays below ``min_bps`` for ``window`` seconds.

    A read timeout alone misses connections that trickle a few bytes at a time, and a
    check inside the read loop never runs while the read is blocked. So a thread watches
    the byte counter and closes the socket, which unblocks the read.
    """

    def __init__(self, response, min_bps: int = 20_000, window: float = 60.0, interval: float = 5.0) -> None:
        super().__init__(daemon=True)
        self.response, self.min_bps, self.window, self.interval = response, min_bps, window, interval
        self.bytes = 0
        self.stalled = False
        self._done = threading.Event()

    def add(self, n: int) -> None:
        self.bytes += n

    def run(self) -> None:
        mark_b, mark_t = 0, time.monotonic()
        while not self._done.wait(self.interval):
            now = time.monotonic()
            if now - mark_t >= self.window:
                if (self.bytes - mark_b) / (now - mark_t) < self.min_bps:
                    self.stalled = True
                    self._kill()
                    return
                mark_b, mark_t = self.bytes, now

    def _kill(self) -> None:
        try:
            self.response.raw.connection.sock.shutdown(socket.SHUT_RDWR)
        except Exception:  # best effort: the connection may already be gone
            pass
        try:
            self.response.close()
        except Exception:
            pass

    def stop(self) -> None:
        self._done.set()


def download(url: str, dest: Path, retries: int = 20) -> Path:
    """Download ``url`` to ``dest``, resuming a ``.part`` file with HTTP Range.

    dumps.wikimedia.org cuts long transfers (observed at exactly 256 MiB), so a
    plain retry would restart from zero forever. Skips if ``dest`` already exists.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    tmp = dest.with_name(dest.name + ".part")
    t0 = time.monotonic()
    for attempt in range(retries):
        have = tmp.stat().st_size if tmp.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with _session.get(url, stream=True, timeout=(30, 30), headers=headers) as r:
                if r.status_code == 416:  # nothing left to fetch
                    break
                r.raise_for_status()
                if have and r.status_code != 206:  # server ignored Range: start over
                    have = 0
                total = have + int(r.headers.get("Content-Length", 0))
                watchdog = _Watchdog(r)
                watchdog.start()
                try:
                    with open(tmp, "ab" if have else "wb") as f:
                        for chunk in r.iter_content(1 << 16):
                            f.write(chunk)
                            watchdog.add(len(chunk))
                except Exception as e:
                    if watchdog.stalled:
                        raise _Stalled(f"below {watchdog.min_bps} B/s for {watchdog.window:.0f}s") from e
                    raise
                finally:
                    watchdog.stop()
                if watchdog.stalled:
                    raise _Stalled(f"below {watchdog.min_bps} B/s for {watchdog.window:.0f}s")
            if tmp.stat().st_size >= total:
                break
            log.info("download cut at %d bytes, resuming %s", tmp.stat().st_size, url)
        except (requests.RequestException, _Stalled) as e:
            if attempt == retries - 1:
                raise
            log.warning("download error (%s), retry %d: %s", e, attempt + 1, url)
            time.sleep(min(30, 2 * (attempt + 1)))
    else:
        raise RuntimeError(f"incomplete download after {retries} attempts: {url}")
    tmp.rename(dest)
    log.debug("downloaded %s in %.1fs", dest.name, time.monotonic() - t0)
    return dest


def rest_hourly_total(project: str, ts_hour_start: datetime, agent: str = "user") -> int | None:
    """Project-level hourly views from the REST API (used to verify hour alignment)."""
    stamp = ts_hour_start.strftime("%Y%m%d%H")
    url = f"{REST_BASE}/aggregate/{project}/all-access/{agent}/hourly/{stamp}/{stamp}"
    r = _session.get(url, timeout=30)
    if not r.ok:
        return None
    items = r.json().get("items", [])
    return int(items[0]["views"]) if items else None


def utcnow() -> datetime:
    """Current time as naive UTC (the whole package uses naive UTC datetimes)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
