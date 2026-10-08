"""D7: backfill the lake from pageview_complete (one bz2 per day, hourly counts inside).

Resumable by construction: a day is skipped when all its 24 hours are already in the
manifest, a partial download resumes with HTTP Range, and each day is committed on
its own. Re-run the same command to continue after an interruption::

    python -m lookedup.backfill --from 2026-07-09 --to 2026-10-06

Hours already ingested by the hourly job are never overwritten. ``validate`` compares
random backfilled hours with the hourly-dump path (they must match exactly).
"""

from __future__ import annotations

import argparse
import logging
import random
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from lookedup import dumps
from lookedup.languages import active_codes, article_filter
from lookedup.parse import ArticleFilter
from lookedup.settings import RAW_DIR
from lookedup.store import Store, day_path, open_store, write_hours
from lookedup.transform import hourly_dump_to_table, pageview_complete_to_tables

log = logging.getLogger(__name__)


def day_range(start: date, end: date, newest_first: bool = True) -> list[date]:
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    return days[::-1] if newest_first else days


def backfill_day(store: Store, day: date, langs: list[str], filt: ArticleFilter,
                 keep_raw: bool = False) -> int:
    """Ingest the missing hours of one day. Returns the number of hours written."""
    present = store.read_manifest().present()
    hours = [datetime(day.year, day.month, day.day) + timedelta(hours=h) for h in range(24)]
    missing = [ts for ts in hours if ts not in present]
    if not missing:
        log.info("day=%s complete, skipping", day)
        return 0
    t0 = time.monotonic()
    url = dumps.pvc_url(day)
    raw = dumps.download(url, RAW_DIR / "pageview_complete" / url.rsplit("/", 1)[1])
    t1 = time.monotonic()
    tables = pageview_complete_to_tables(raw, day, langs, filt)
    t2 = time.monotonic()
    written = write_hours(store, {ts: (tables[ts], "pageview_complete") for ts in missing},
                          f"data: backfill {day} ({len(missing)} hours) from pageview_complete")
    rows = sum(tables[ts].num_rows for ts in written)
    log.info("day=%s hours=%d rows=%d download=%.0fs process=%.0fs source=pageview_complete",
             day, len(missing), rows, t1 - t0, t2 - t1)
    if not keep_raw:
        raw.unlink(missing_ok=True)
    return len(written)


def backfill(store: Store, start: date, end: date, newest_first: bool = True, keep_raw: bool = False) -> int:
    langs, filt = active_codes(), article_filter()
    days = day_range(start, end, newest_first)
    total = 0
    for i, day in enumerate(days, 1):
        total += backfill_day(store, day, langs, filt, keep_raw)
        log.info("progress: %d/%d days", i, len(days))
    return total


def validate(store: Store, n: int = 3, seed: int | None = None) -> list[dict]:
    """Rebuild ``n`` random backfilled hours from the hourly dumps and compare exactly."""
    manifest = store.read_manifest()
    candidates = sorted(k for k, v in manifest.hours.items() if v["source"] == "pageview_complete")
    picks = random.Random(seed).sample(candidates, min(n, len(candidates)))
    langs, filt = active_codes(), article_filter()
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for key in picks:
            ts = datetime.strptime(key, "%Y-%m-%dT%H:%M:%SZ")
            day_file = pq.read_table(store.fetch(day_path(ts), Path(tmp)))
            stored = day_file.filter(pc.equal(day_file["ts_hour_start"], pa.scalar(ts, pa.timestamp("us"))))
            raw = dumps.download(dumps.file_url(ts), Path(tmp) / dumps.file_name(ts))
            rebuilt = hourly_dump_to_table(raw, ts, langs, filt)

            def rows(t):
                return sorted(zip(*(t[c].to_pylist() for c in
                                    ("ts_hour_start", "lang", "title", "views_desktop", "views_mobile"))))
            a, b = rows(stored), rows(rebuilt)
            only_a, only_b = set(a) - set(b), set(b) - set(a)
            views = lambda rs: sum(r[3] + r[4] for r in rs)  # noqa: E731
            res = {"hour": key, "stored_rows": len(a), "rebuilt_rows": len(b), "identical": a == b,
                   "rows_only_in_stored": len(only_a), "rows_only_in_rebuilt": len(only_b),
                   "matching_rows_pct": round(100 * len(set(a) & set(b)) / max(len(b), 1), 4),
                   "views_stored": views(a), "views_rebuilt": views(b),
                   "differing_rows_sample": sorted(only_a | only_b)[:5]}
            log.info("validate %s", res)
            results.append(res)
    return results


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m lookedup.backfill", description=__doc__.splitlines()[0])
    p.add_argument("--from", dest="start", required=True, type=date.fromisoformat)
    p.add_argument("--to", dest="end", required=True, type=date.fromisoformat)
    p.add_argument("--oldest-first", action="store_true", help="default is newest day first")
    p.add_argument("--keep-raw", action="store_true", help="keep downloaded bz2 files")
    p.add_argument("--local", action="store_true", help="write to data/lake/ instead of Hugging Face")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    n = backfill(open_store(args.local), args.start, args.end, not args.oldest_first, args.keep_raw)
    log.info("backfill finished: %d hours written", n)


if __name__ == "__main__":
    main()
