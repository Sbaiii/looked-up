"""Q1b: does compacting several hours into one Parquet file shrink storage?

Compares (a) one Parquet per hour vs (b) the same hours in one file with an hour
column, sorted by (lang, title, hour), for Wikipedia top-50 languages, desktop+mobile summed.
Uses whatever hourly files q1 already downloaded into data/raw/pageviews/.

Usage: .venv/bin/python spike/q1b_compaction.py
"""

from __future__ import annotations

import json

import duckdb

from common import DERIVED, RAW

files = sorted((RAW / "pageviews").glob("pageviews-*.gz"))[-3:]
summary = json.loads((DERIVED / "q1_summary.json").read_text())
langs = ",".join(f"'{l}'" for l, _, _ in summary["top50_langs"])

con = duckdb.connect()
sep_total = 0
for i, f in enumerate(files):
    hour = f.stem.split("-")[2][:2]
    con.execute(f"""
        CREATE OR REPLACE TABLE h{i} AS
        SELECT split_part(project, '.', 1) AS lang, page_title, '{hour}'::UTINYINT AS hour,
               sum(views)::INTEGER AS views
        FROM read_csv('{f}', delim=' ', header=false, quote='', escape='', auto_detect=false,
             columns={{'project':'VARCHAR','page_title':'VARCHAR','views':'BIGINT','bytes':'BIGINT'}},
             ignore_errors=true)
        WHERE regexp_matches(project, '^[a-z0-9-]+(\\.m)?$') AND split_part(project, '.', 1) IN ({langs})
        GROUP BY ALL
    """)
    out = DERIVED / f"compact_sep_{i}.parquet"
    con.execute(f"COPY (SELECT lang, page_title, views FROM h{i} ORDER BY 1,2) TO '{out}' (FORMAT parquet, COMPRESSION zstd)")
    sep_total += out.stat().st_size

union = " UNION ALL ".join(f"SELECT * FROM h{i}" for i in range(len(files)))
res = {"hours": len(files), "separate_bytes": sep_total}
for level in [3, 9, 19]:
    out = DERIVED / f"compact_combined_l{level}.parquet"
    con.execute(f"""COPY (SELECT * FROM ({union}) ORDER BY lang, page_title, hour)
                    TO '{out}' (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL {level}, ROW_GROUP_SIZE 1000000)""")
    res[f"combined_zstd{level}_bytes"] = out.stat().st_size
res["ratio_combined_l9_vs_separate"] = round(res["combined_zstd9_bytes"] / sep_total, 3)
res["est_gb_year_combined_l9"] = round(
    res["combined_zstd9_bytes"] / len(files) * summary["day_factor_vs_newest_hour"] * 365 / 1e9, 0)
(DERIVED / "q1b_compaction.json").write_text(json.dumps(res, indent=2))
print(json.dumps(res, indent=2))
