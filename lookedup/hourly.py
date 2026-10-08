"""D6: the hourly ingestion job. Idempotent and self-healing.

Each run: expected hours (last 72 h) - hours in the manifest = missing; of those, the
ones already published on dumps.wikimedia.org are processed, newest first, at most 6
per run, merged into their day files and committed in a single commit (day files + manifest).
Hours already present are never reprocessed, so a late, skipped or repeated run is harmless.
"""

from __future__ import annotations

import logging
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import pyarrow as pa

from lookedup import db, dumps
from lookedup.languages import active_codes, article_filter
from lookedup.parse import ArticleFilter
from lookedup.settings import MAX_HOURS_PER_RUN, MIN_VIEWS, WINDOW_HOURS
from lookedup.store import Manifest, Store, expected_hours, missing_hours, write_hours
from lookedup.transform import hourly_dump_to_table

log = logging.getLogger(__name__)

LATE_AFTER_MINUTES = 6 * 60  # warn when an hour is still unpublished this long after it ended


def plan(manifest: Manifest, now: datetime, window_hours: int = WINDOW_HOURS,
         max_hours: int = MAX_HOURS_PER_RUN) -> tuple[list[dumps.HourlyFile], list[datetime]]:
    """Return (files to process now, newest first; hours still unpublished)."""
    expected = expected_hours(now, window_hours)
    missing = missing_hours(manifest, expected)
    if not missing:
        return [], []
    available = dumps.available_hours(missing[0], missing[-1] + timedelta(hours=1))
    todo = sorted((available[ts] for ts in missing if ts in available),
                  key=lambda f: f.ts_hour_start, reverse=True)
    unpublished = [ts for ts in missing if ts not in available]
    return todo[:max_hours], unpublished


def process_hour(f: dumps.HourlyFile, langs: list[str], filt: ArticleFilter, work_dir: Path,
                 min_views: int = MIN_VIEWS) -> pa.Table:
    """Download one hourly dump and build its retained table. The raw file is deleted."""
    t0 = time.monotonic()
    raw = dumps.download(f.url, work_dir / f.name)
    t1 = time.monotonic()
    table = hourly_dump_to_table(raw, f.ts_hour_start, langs, filt, min_views)
    t2 = time.monotonic()
    raw.unlink(missing_ok=True)
    log.info("hour=%s rows=%d lag=%dmin gz=%d download=%.1fs process=%.1fs source=hourly_dump",
             f"{f.ts_hour_start:%Y-%m-%dT%H:00Z}", table.num_rows, f.lag_minutes, f.size, t1 - t0, t2 - t1)
    return table


def run(store: Store, now: datetime | None = None, langs: list[str] | None = None,
        filt: ArticleFilter | None = None, window_hours: int = WINDOW_HOURS,
        max_hours: int = MAX_HOURS_PER_RUN) -> int:
    """One run of the hourly job. Returns the number of hours ingested."""
    now = now or dumps.utcnow()
    langs = langs or active_codes()
    filt = filt or article_filter()
    manifest = store.read_manifest()
    todo, unpublished = plan(manifest, now, window_hours, max_hours)
    for ts in unpublished:
        age = (now - ts - timedelta(hours=1)).total_seconds() / 60
        if age > LATE_AFTER_MINUTES:
            log.warning("hour=%s still unpublished %.0f min after it ended", f"{ts:%Y-%m-%dT%H:00Z}", age)
    log.info("plan: %d hours to ingest now, %d not yet published, %d present in manifest",
             len(todo), len(unpublished), len(manifest.hours))
    if not todo:
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        tables = {f.ts_hour_start: (process_hour(f, langs, filt, Path(tmp)), "hourly_dump") for f in todo}
    first, last = min(tables), max(tables)
    written = write_hours(store, tables, f"data: ingest {len(tables)} hour(s) {first:%Y-%m-%dT%H}..{last:%Y-%m-%dT%H}Z")
    return len(written)


def verify_alignment(ts_hour_start: datetime, work_dir: Path) -> dict:
    """Check 'filename = end of hour' against the REST API for one hour (en.wikipedia total)."""
    f = dumps.HourlyFile(name=dumps.file_name(ts_hour_start), url=dumps.file_url(ts_hour_start),
                         ts_hour_start=ts_hour_start, posted=ts_hour_start, size=0)
    raw = dumps.download(f.url, work_dir / f.name)
    total = db.connect().sql(f"""
        SELECT sum(views) FROM read_csv('{raw}', delim=' ', header=false, quote='', escape='',
            auto_detect=false, columns={{'p':'VARCHAR','t':'VARCHAR','views':'BIGINT','b':'BIGINT'}},
            ignore_errors=true) WHERE p IN ('en', 'en.m')""").fetchone()[0]
    return {
        "file": f.name,
        "dump_en_total": int(total),
        "rest_same_hour_start": dumps.rest_hourly_total("en.wikipedia", ts_hour_start),
        "rest_hour_after": dumps.rest_hourly_total("en.wikipedia", ts_hour_start + timedelta(hours=1)),
    }
