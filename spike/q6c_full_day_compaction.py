"""Q6c: real full-day compaction (24 hourly Parquet files -> 1 day file) and its timing.

Uses the 24 hourly dumps of 2026-08-28 (downloaded by q5) and the article-based top-50
language list from q1c. Measures per-hour Parquet total vs one compacted day file, plus the
>= 5 views/hour retention tier on a full day.

Usage: .venv/bin/python spike/q6c_full_day_compaction.py
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import duckdb

from common import DERIVED, RAW

day = datetime(2026, 8, 28)
langs = ",".join(f"'{l}'" for l, _, _ in json.loads((DERIVED / "q1c_language_set.json").read_text())["top50"])
out_dir = DERIVED / "fullday" / f"date={day:%Y-%m-%d}"
out_dir.mkdir(parents=True, exist_ok=True)
con = duckdb.connect()

t0 = time.perf_counter()
hourly_bytes = 0
for h in range(24):
    src = RAW / "pageviews" / f"pageviews-{(day + timedelta(hours=h + 1)):%Y%m%d-%H}0000.gz"
    dst = out_dir / f"hour={h:02d}.parquet"
    con.execute(f"""
        COPY (
            SELECT split_part(project, '.', 1) AS lang, page_title, {h}::UTINYINT AS hour, sum(views)::INTEGER AS views
            FROM read_csv('{src}', delim=' ', header=false, quote='', escape='', auto_detect=false,
                 columns={{'project':'VARCHAR','page_title':'VARCHAR','views':'BIGINT','bytes':'BIGINT'}},
                 ignore_errors=true)
            WHERE regexp_matches(project, '^[a-z0-9-]+(\\.m)?$') AND split_part(project, '.', 1) IN ({langs})
            GROUP BY ALL ORDER BY lang, page_title
        ) TO '{dst}' (FORMAT parquet, COMPRESSION zstd)
    """)
    hourly_bytes += dst.stat().st_size
hourly_s = time.perf_counter() - t0

res = {"day": f"{day:%Y-%m-%d}", "hourly_files_bytes": hourly_bytes, "hourly_convert_s": round(hourly_s, 1)}
for name, where in [("all", "true"), ("min5", "views >= 5")]:
    t = time.perf_counter()
    dst = DERIVED / "fullday" / f"day={day:%Y-%m-%d}-{name}.parquet"
    con.execute(f"""
        COPY (SELECT * FROM read_parquet('{out_dir}/hour=*.parquet') WHERE {where} ORDER BY lang, page_title, hour)
        TO '{dst}' (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 9, ROW_GROUP_SIZE 1000000)
    """)
    res[f"day_{name}_bytes"] = dst.stat().st_size
    res[f"day_{name}_compact_s"] = round(time.perf_counter() - t, 1)
    res[f"day_{name}_gb_year"] = round(dst.stat().st_size * 365 / 1e9, 1)
res["compaction_ratio_all"] = round(res["day_all_bytes"] / hourly_bytes, 3)
res["rows_all"] = con.execute(f"SELECT count(*) FROM read_parquet('{out_dir}/hour=*.parquet')").fetchone()[0]
(DERIVED / "q6c_full_day.json").write_text(json.dumps(res, indent=2))
print(json.dumps(res, indent=2))
