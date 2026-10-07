"""Q6: time the full hourly job end to end on this machine.

download latest hourly file -> filter Wikipedia top-50 langs (desktop+mobile summed)
-> write hourly Parquet -> append into the day's partition -> compact the day so far.

Usage: .venv/bin/python spike/q6_hourly_job.py [--fresh]
  --fresh  delete the cached hourly file first so download time is measured.
"""

from __future__ import annotations

import json
import resource
import sys
import time
from datetime import datetime, timedelta, timezone

import duckdb

from common import DERIVED, RAW, download, list_hourly

WP_FILTER = "regexp_matches(project, '^[a-z0-9-]+(\\.m)?$')"


def main() -> None:
    timings: dict[str, float] = {}
    t_all = time.perf_counter()

    now = datetime.now(timezone.utc)
    t = time.perf_counter()
    latest = list_hourly(now.year, now.month)[-1]
    timings["list_s"] = time.perf_counter() - t

    dest = RAW / "pageviews" / latest["name"]
    if "--fresh" in sys.argv and dest.exists():
        dest.unlink()
    _, timings["download_s"] = download(latest["url"], dest)

    langs = json.loads((DERIVED / "q1_summary.json").read_text())["top50_langs"]
    lang_list = ",".join(f"'{l}'" for l, _, _ in langs)
    hour_start = latest["hour"] - timedelta(hours=1)  # filename = end of hour
    part = DERIVED / "lake" / f"date={hour_start:%Y-%m-%d}"
    part.mkdir(parents=True, exist_ok=True)
    out = part / f"hour={hour_start:%H}.parquet"

    con = duckdb.connect()
    t = time.perf_counter()
    con.execute(f"""
        COPY (
            SELECT split_part(project, '.', 1) AS lang, page_title, {hour_start.hour}::UTINYINT AS hour,
                   sum(views)::INTEGER AS views
            FROM read_csv('{dest}', delim=' ', header=false, quote='', escape='', auto_detect=false,
                 columns={{'project':'VARCHAR','page_title':'VARCHAR','views':'BIGINT','bytes':'BIGINT'}},
                 ignore_errors=true)
            WHERE {WP_FILTER} AND split_part(project, '.', 1) IN ({lang_list})
            GROUP BY ALL
            ORDER BY lang, page_title
        ) TO '{out}' (FORMAT parquet, COMPRESSION zstd)
    """)
    timings["filter_to_parquet_s"] = time.perf_counter() - t

    # "append": the hourly file lands in the day's partition; then compact the day so far
    t = time.perf_counter()
    day_file = DERIVED / "lake" / f"day={hour_start:%Y-%m-%d}.parquet"
    con.execute(f"""
        COPY (SELECT * FROM read_parquet('{part}/hour=*.parquet') ORDER BY lang, page_title, hour)
        TO '{day_file}' (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 9)
    """)
    timings["compact_day_s"] = time.perf_counter() - t
    hours_in_day = len(list(part.glob("hour=*.parquet")))

    timings["total_s"] = time.perf_counter() - t_all
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    res = {
        "file": latest["name"], "hour_start_utc": hour_start.isoformat(),
        "gz_bytes": dest.stat().st_size, "hour_parquet_bytes": out.stat().st_size,
        "day_parquet_bytes": day_file.stat().st_size, "hours_in_day_partition": hours_in_day,
        "rows": con.execute(f"SELECT count(*) FROM '{out}'").fetchone()[0],
        "peak_rss_mb": round(rss / (1024 * 1024 if sys.platform == "darwin" else 1024), 0),
        **{k: round(v, 2) for k, v in timings.items()},
    }
    (DERIVED / "q6_hourly_job.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
