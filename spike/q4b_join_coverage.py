"""Q4b: what share of pageviews joins onto a Wikidata QID by (site, title)?

Joins the q1 hour (top-50 Wikipedias, desktop+mobile summed) to the sitelink Parquet built
by `q4_wikidata.py --full`. Unmatched views are mostly redirects, special/namespace pages and
title variants. Reports coverage by views and by rows, and the top unmatched titles.

Usage: .venv/bin/python spike/q4b_join_coverage.py
"""

from __future__ import annotations

import json

import duckdb

from common import DERIVED

con = duckdb.connect()
con.execute(f"""
    CREATE TABLE pv AS
    SELECT lang, page_title, views, replace(lang, '-', '_') || 'wiki' AS site
    FROM '{DERIVED / "pv_wp50_summed.parquet"}'
""")
con.execute(f"CREATE TABLE sl AS SELECT * FROM '{DERIVED / 'sitelinks_wikipedia_top50.parquet'}'")
con.execute("""
    CREATE TABLE j AS
    SELECT pv.*, sl.qid,
           -- namespace prefix (anything before ':' that is not part of a normal title) is approximate
           regexp_matches(page_title, '^[^:_]+:') AS has_prefix
    FROM pv LEFT JOIN sl ON sl.site = pv.site AND sl.title = pv.page_title
""")
tot_v, tot_r = con.execute("SELECT sum(views), count(*) FROM j").fetchone()
m_v, m_r = con.execute("SELECT sum(views), count(*) FROM j WHERE qid IS NOT NULL").fetchone()
np_v = con.execute("SELECT sum(views) FROM j WHERE NOT has_prefix").fetchone()[0]
np_m = con.execute("SELECT sum(views) FROM j WHERE NOT has_prefix AND qid IS NOT NULL").fetchone()[0]
res = {
    "views_matched_pct": round(100 * m_v / tot_v, 1),
    "rows_matched_pct": round(100 * m_r / tot_r, 1),
    "views_matched_pct_excluding_prefixed_titles": round(100 * np_m / np_v, 1),
    "distinct_qids_seen_in_hour": con.execute("SELECT count(DISTINCT qid) FROM j").fetchone()[0],
    "top_unmatched": con.execute("""
        SELECT lang, page_title, views FROM j WHERE qid IS NULL ORDER BY views DESC LIMIT 25
    """).fetchall(),
    "by_lang": con.execute("""
        SELECT lang, round(100 * sum(views) FILTER (WHERE qid IS NOT NULL) / sum(views), 1) AS pct
        FROM j GROUP BY 1 ORDER BY sum(views) DESC LIMIT 12
    """).fetchall(),
}
(DERIVED / "q4b_join_coverage.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
print(json.dumps(res, indent=2, ensure_ascii=False))
