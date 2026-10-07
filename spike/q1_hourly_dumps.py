"""Q1: hourly pageview dumps — size, shape, lag, DuckDB load, Parquet extrapolation.

Usage: .venv/bin/python spike/q1_hourly_dumps.py
Writes a JSON summary to data/derived/q1_summary.json and prints a report.
"""

from __future__ import annotations

import gzip
import json
import time
from datetime import datetime, timedelta, timezone

import duckdb

from common import DERIVED, RAW, download, human, list_hourly, session

# ".m" also tags non-Wikipedia Wikimedia sites (commons.m, meta.m, ...). Exclude them
# so "Wikipedia only" really means language Wikipedias.
NON_WIKIPEDIA = {
    "commons", "meta", "species", "incubator", "outreach", "wikimania", "wikidata",
    "foundation", "mediawiki", "wikisource", "wikitech", "login", "sources", "beta",
    "nostalgia", "strategy", "usability", "quality", "office", "ten", "test", "test2",
    "advisory", "donate", "api", "vote", "wikifunctions", "auth",
}


def latest_files(n: int = 3) -> list[dict]:
    now = datetime.now(timezone.utc)
    files = list_hourly(now.year, now.month)
    if len(files) < n:
        prev = now.replace(day=1) - timedelta(days=1)
        files = list_hourly(prev.year, prev.month) + files
    return files[-n:]


def day_listing(day: datetime) -> list[dict]:
    files = [f for f in list_hourly(day.year, day.month) if f["hour"].date() == day.date()]
    return files


def scan_raw(path):
    """Uncompressed bytes, line count, projects (pure Python streaming pass)."""
    raw_bytes = lines = 0
    projects: dict[str, int] = {}
    with gzip.open(path, "rb") as f:
        for line in f:
            raw_bytes += len(line)
            lines += 1
            sp = line.find(b" ")
            p = line[:sp]
            projects[p] = projects.get(p, 0) + 1
    return raw_bytes, lines, projects


def load_sql(path) -> str:
    return f"""
        SELECT * FROM read_csv('{path}',
            delim=' ', header=false, quote='', escape='', auto_detect=false,
            columns={{'project':'VARCHAR','page_title':'VARCHAR','views':'BIGINT','bytes':'BIGINT'}},
            ignore_errors=true, compression='gzip')
    """


def main() -> None:
    DERIVED.mkdir(parents=True, exist_ok=True)
    report: dict = {"run_at": datetime.now(timezone.utc).isoformat()}

    # ---- 1a: latest 3 files, sizes, lines, projects, lag --------------------------
    files = latest_files(3)
    rows = []
    for f in files:
        dest = RAW / "pageviews" / f["name"]
        _, secs = download(f["url"], dest)
        raw_bytes, lines, projects = scan_raw(dest)
        # filename timestamp = END of the hour covered (Wikitech); lag measured from it
        lag = f["posted"] - f["hour"]
        rows.append({
            "file": f["name"],
            "covers_utc": f"{(f['hour'] - timedelta(hours=1)):%Y-%m-%d %H:00}–{f['hour']:%H:00}",
            "posted_utc": f"{f['posted']:%Y-%m-%d %H:%M}",
            "lag_after_hour_end_min": int(lag.total_seconds() // 60),
            "gz_bytes": dest.stat().st_size,
            "raw_bytes": raw_bytes,
            "lines": lines,
            "projects": len(projects),
            "download_s": round(secs, 1),
        })
        print(rows[-1])
    report["files"] = rows

    # lag distribution over the last 7 full days of listings
    now = datetime.now(timezone.utc)
    hist = []
    for d in range(1, 8):
        hist += day_listing(now - timedelta(days=d))
    lags = sorted((f["posted"] - f["hour"]).total_seconds() / 60 for f in hist)
    report["lag_7d_min"] = {
        "n": len(lags), "min": lags[0], "median": lags[len(lags) // 2],
        "p90": lags[int(len(lags) * 0.9)], "max": lags[-1],
    }
    # daily gz volume (yesterday) to scale hourly measurements to a real day
    yday = day_listing(now - timedelta(days=1))
    report["yesterday_gz_total"] = sum(f["gz_bytes"] for f in yday)
    report["yesterday_files"] = len(yday)

    # project breakdown on newest file
    newest = RAW / "pageviews" / files[-1]["name"]
    con = duckdb.connect()

    # ---- 1b: DuckDB load + Parquet zstd -------------------------------------------
    t0 = time.perf_counter()
    con.execute(f"CREATE TABLE pv AS {load_sql(newest)}")
    load_s = time.perf_counter() - t0
    n = con.execute("SELECT count(*) FROM pv").fetchone()[0]
    report["duckdb_load_s"] = round(load_s, 2)
    report["duckdb_rows"] = n
    report["bytes_col_nonzero"] = con.execute("SELECT count(*) FROM pv WHERE bytes <> 0").fetchone()[0]

    proj = con.execute("""
        SELECT project, count(*) AS rows, sum(views) AS views FROM pv
        GROUP BY 1 ORDER BY views DESC
    """).fetchall()
    report["distinct_projects_newest"] = len(proj)
    report["top_projects"] = proj[:25]

    def suffix(p: str) -> str:
        parts = p.split(".", 1)
        return parts[1] if len(parts) > 1 else "(none)"

    suff: dict[str, list[int]] = {}
    for p, r, v in proj:
        s = suffix(p)
        suff.setdefault(s, [0, 0])
        suff[s][0] += r
        suff[s][1] += v
    report["suffix_breakdown"] = sorted(([s, r, v] for s, (r, v) in suff.items()), key=lambda x: -x[2])

    out_all = DERIVED / "pv_all.parquet"
    t0 = time.perf_counter()
    con.execute(f"""COPY (SELECT project, page_title, views FROM pv ORDER BY project, page_title)
                    TO '{out_all}' (FORMAT parquet, COMPRESSION zstd)""")
    report["parquet_all_s"] = round(time.perf_counter() - t0, 2)
    report["parquet_all_bytes"] = out_all.stat().st_size

    # Wikipedia only (lang or lang.m), top 50 languages by views
    excl = ",".join(f"'{x}'" for x in NON_WIKIPEDIA)
    con.execute(f"""
        CREATE TABLE wp AS
        SELECT split_part(project, '.', 1) AS lang,
               project LIKE '%.m' AS mobile, page_title, views
        FROM pv
        WHERE (project NOT LIKE '%.%' OR (project LIKE '%.m' AND length(project) - length(replace(project, '.', '')) = 1))
          AND split_part(project, '.', 1) NOT IN ({excl})
          AND regexp_matches(project, '^[a-z0-9-]+(\\.m)?$')
    """)
    top50 = con.execute("""
        SELECT lang, sum(views) v, sum(views) FILTER (WHERE mobile) mv FROM wp
        GROUP BY 1 ORDER BY v DESC LIMIT 50
    """).fetchall()
    report["top50_langs"] = [[l, int(v), round(100 * (mv or 0) / v, 1)] for l, v, mv in top50]
    langs = ",".join(f"'{l}'" for l, _, _ in top50)
    total_wp = con.execute("SELECT sum(views) FROM wp").fetchone()[0]
    total_all = con.execute("SELECT sum(views) FROM pv").fetchone()[0]
    top50_views = sum(v for _, v, _ in top50)
    report["views_total"] = int(total_all)
    report["views_wikipedia"] = int(total_wp)
    report["views_top50"] = int(top50_views)
    report["wikipedia_langs_present"] = con.execute("SELECT count(DISTINCT lang) FROM wp").fetchone()[0]

    # Variant A: keep desktop/mobile rows separate
    out_wp = DERIVED / "pv_wp50.parquet"
    con.execute(f"""COPY (SELECT lang, mobile, page_title, views FROM wp WHERE lang IN ({langs})
                    ORDER BY lang, page_title) TO '{out_wp}' (FORMAT parquet, COMPRESSION zstd)""")
    report["parquet_wp50_bytes"] = out_wp.stat().st_size
    report["rows_wp50"] = con.execute(f"SELECT count(*) FROM wp WHERE lang IN ({langs})").fetchone()[0]

    # Variant B: desktop+mobile summed per (lang, title)
    out_wp_sum = DERIVED / "pv_wp50_summed.parquet"
    con.execute(f"""COPY (SELECT lang, page_title, sum(views)::INTEGER AS views FROM wp WHERE lang IN ({langs})
                    GROUP BY 1, 2 ORDER BY 1, 2) TO '{out_wp_sum}' (FORMAT parquet, COMPRESSION zstd)""")
    report["parquet_wp50_summed_bytes"] = out_wp_sum.stat().st_size
    report["rows_wp50_summed"] = con.execute(
        f"SELECT count(*) FROM (SELECT DISTINCT lang, page_title FROM wp WHERE lang IN ({langs}))").fetchone()[0]

    # Variant C: summed + drop titles with views < 2 in the hour (long tail)
    out_wp_min = DERIVED / "pv_wp50_min2.parquet"
    con.execute(f"""COPY (SELECT lang, page_title, sum(views)::INTEGER AS views FROM wp WHERE lang IN ({langs})
                    GROUP BY 1, 2 HAVING sum(views) >= 2 ORDER BY 1, 2) TO '{out_wp_min}' (FORMAT parquet, COMPRESSION zstd)""")
    report["parquet_wp50_min2_bytes"] = out_wp_min.stat().st_size

    # Mobile/desktop split per top language
    report["mobile_share_wikipedia_pct"] = round(
        100 * con.execute("SELECT sum(views) FILTER (WHERE mobile) / sum(views) FROM wp").fetchone()[0], 1)
    report["titles_on_both"] = con.execute("""
        SELECT count(*) FROM (SELECT lang, page_title FROM wp GROUP BY 1,2 HAVING count(DISTINCT mobile) = 2)
    """).fetchone()[0]

    # ---- extrapolation -------------------------------------------------------------
    # Scale by the gz volume of a whole real day vs this hour's gz (captures diurnal cycle).
    hour_gz = newest.stat().st_size
    day_factor = report["yesterday_gz_total"] / hour_gz if report["yesterday_files"] == 24 else 24
    report["day_factor_vs_newest_hour"] = round(day_factor, 2)
    for key in ["parquet_all_bytes", "parquet_wp50_bytes", "parquet_wp50_summed_bytes", "parquet_wp50_min2_bytes"]:
        per_day = report[key] * day_factor
        report[key.replace("_bytes", "_gb_day")] = round(per_day / 1e9, 2)
        report[key.replace("_bytes", "_gb_year")] = round(per_day * 365 / 1e9, 0)

    # ---- filename semantics + agent check against REST aggregate hourly API ---------
    # The per-article endpoint has no hourly granularity, so compare the en.wikipedia
    # total (en + en.m) in the newest file with aggregate hourly values per agent.
    fhour = files[-1]["hour"]
    dump_en = con.execute("SELECT sum(views) FROM pv WHERE project IN ('en','en.m')").fetchone()[0]
    start = (fhour - timedelta(hours=2)).strftime("%Y%m%d%H")
    end = fhour.strftime("%Y%m%d%H")
    api = {}
    for agent in ["user", "automated", "spider", "all-agents"]:
        r = session.get(
            "https://wikimedia.org/api/rest_v1/metrics/pageviews/aggregate/en.wikipedia/"
            f"all-access/{agent}/hourly/{start}/{end}", timeout=30)
        api[agent] = {i["timestamp"]: i["views"] for i in r.json().get("items", [])} if r.ok else r.status_code
    matches = [(a, ts) for a, d in api.items() if isinstance(d, dict) for ts, v in d.items() if v == dump_en]
    report["filename_check"] = {"file_hour": fhour.isoformat(), "dump_en_total": int(dump_en),
                                "api": api, "exact_matches": matches}
    print("filename check exact matches (agent, API hour-start):", matches)

    (DERIVED / "q1_summary.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({k: v for k, v in report.items() if k not in ("top_projects", "top50_langs")},
                     indent=2, default=str))
    print("all-projects parquet/hour:", human(report["parquet_all_bytes"]))


if __name__ == "__main__":
    main()
