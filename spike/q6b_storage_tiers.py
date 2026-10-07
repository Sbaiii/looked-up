"""Q6b: how small can the stored lake be? Size of derived tiers per year.

Wikimedia already archives every raw hourly file since 2015, so we only need to store
what we derive. Measures, on the 3 hours from q1 (top-50 Wikipedias, desktop+mobile summed):
  * hourly rows kept only when views >= N  (N = 1, 2, 5, 10, 25)
  * a daily (lang, title, views) rollup estimate
and extrapolates to GB/year using the real day's gz volume factor from q1.

Usage: .venv/bin/python spike/q6b_storage_tiers.py
"""

from __future__ import annotations

import json

import duckdb

from common import DERIVED, RAW

q1 = json.loads((DERIVED / "q1_summary.json").read_text())
langs = ",".join(f"'{l}'" for l, _, _ in q1["top50_langs"])
recent = [RAW / "pageviews" / x["file"] for x in q1["files"]]  # the 3 hours q1 measured
assert all(f.exists() for f in recent), recent

con = duckdb.connect()
union = " UNION ALL ".join(f"""
    SELECT split_part(project, '.', 1) AS lang, page_title, {int(f.stem.split('-')[2][:2])}::UTINYINT AS hour,
           views
    FROM read_csv('{f}', delim=' ', header=false, quote='', escape='', auto_detect=false,
         columns={{'project':'VARCHAR','page_title':'VARCHAR','views':'BIGINT','bytes':'BIGINT'}},
         ignore_errors=true)
    WHERE regexp_matches(project, '^[a-z0-9-]+(\\.m)?$') AND split_part(project, '.', 1) IN ({langs})"""
                   for f in recent)
con.execute(f"CREATE TABLE h AS SELECT lang, page_title, hour, sum(views)::INTEGER AS views FROM ({union}) GROUP BY ALL")
total_views = con.execute("SELECT sum(views) FROM h").fetchone()[0]
factor = q1["day_factor_vs_newest_hour"] / 3 * 365  # 3 hours -> one year

res = {"hours": 3, "rows_all": con.execute("SELECT count(*) FROM h").fetchone()[0], "tiers": []}
for n in [1, 2, 5, 10, 25]:
    out = DERIVED / f"tier_min{n}.parquet"
    con.execute(f"""COPY (SELECT * FROM h WHERE views >= {n} ORDER BY lang, page_title, hour)
                    TO '{out}' (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 9)""")
    rows, kept = con.execute(f"SELECT count(*), sum(views) FROM h WHERE views >= {n}").fetchone()
    res["tiers"].append({"min_views_per_hour": n, "rows": rows, "views_kept_pct": round(100 * kept / total_views, 1),
                         "bytes_3h": out.stat().st_size, "gb_year": round(out.stat().st_size * factor / 1e9, 1)})

# Daily rollup: one row per (lang, title) per day. Distinct titles grow sub-linearly with
# hours; use the 3-hour distinct count x 2.5 as a rough full-day estimate (stated in doc).
out = DERIVED / "tier_daily_rollup_3h.parquet"
con.execute(f"""COPY (SELECT lang, page_title, sum(views)::INTEGER AS views FROM h GROUP BY 1, 2 ORDER BY 1, 2)
                TO '{out}' (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 9)""")
res["daily_rollup_3h_bytes"] = out.stat().st_size
res["daily_rollup_gb_year_est"] = round(out.stat().st_size * 2.5 * 365 / 1e9, 1)
out = DERIVED / "tier_daily_rollup_min5_3h.parquet"
con.execute(f"""COPY (SELECT lang, page_title, sum(views)::INTEGER AS views FROM h GROUP BY 1, 2 HAVING sum(views) >= 5
                ORDER BY 1, 2) TO '{out}' (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 9)""")
res["daily_rollup_min5_gb_year_est"] = round(out.stat().st_size * 2.5 * 365 / 1e9, 1)

(DERIVED / "q6b_storage_tiers.json").write_text(json.dumps(res, indent=2))
print(json.dumps(res, indent=2))
