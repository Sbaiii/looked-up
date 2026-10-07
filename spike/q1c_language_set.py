"""Q1c: choose the language set from a full day of hourly files (not one hour).

Uses the 24 hourly files of 2026-08-28 that q5 downloads. Ranks Wikipedias by daily user
views (desktop + mobile), reports cumulative coverage at N = 10/20/30/50/75/100 languages.

Usage: .venv/bin/python spike/q1c_language_set.py [YYYYMMDD]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta

import duckdb

from common import DERIVED, RAW
from q1_hourly_dumps import NON_WIKIPEDIA

day = datetime.strptime(sys.argv[1] if len(sys.argv) > 1 else "20260828", "%Y%m%d")
# hour-start h lives in the file named h+1h
names = [f"pageviews-{(day + timedelta(hours=h + 1)):%Y%m%d-%H}0000.gz" for h in range(24)]
paths = [RAW / "pageviews" / n for n in names]
missing = [p.name for p in paths if not p.exists()]
if missing:
    sys.exit(f"missing {len(missing)} files, e.g. {missing[:3]}; run q5_spike_test.py first")

excl = ",".join(f"'{x}'" for x in NON_WIKIPEDIA)
files = ",".join(f"'{p}'" for p in paths)
con = duckdb.connect()
rows = con.execute(f"""
    SELECT split_part(project, '.', 1) AS lang, sum(views) AS views,
           sum(views) FILTER (WHERE project LIKE '%.m') AS mobile
    FROM read_csv([{files}], delim=' ', header=false, quote='', escape='', auto_detect=false,
         columns={{'project':'VARCHAR','page_title':'VARCHAR','views':'BIGINT','bytes':'BIGINT'}},
         ignore_errors=true)
    WHERE regexp_matches(project, '^[a-z0-9-]+(\\.m)?$') AND split_part(project, '.', 1) NOT IN ({excl})
    GROUP BY 1 ORDER BY 2 DESC
""").fetchall()
total = sum(r[1] for r in rows)
cum, coverage = 0, {}
for i, (_, v, _) in enumerate(rows, 1):
    cum += v
    if i in (10, 20, 30, 50, 75, 100):
        coverage[i] = round(100 * cum / total, 2)
res = {
    "day": f"{day:%Y-%m-%d}", "wikipedias": len(rows), "total_views": int(total), "coverage_pct": coverage,
    "top50": [[l, int(v), round(100 * (m or 0) / v, 1)] for l, v, m in rows[:50]],
    "langs_51_100": [l for l, _, _ in rows[50:100]],
}
(DERIVED / "q1c_language_set.json").write_text(json.dumps(res, indent=2))
print(json.dumps({k: v for k, v in res.items() if k != "top50"}, indent=2))
print(" ".join(l for l, _, _ in res["top50"]))
