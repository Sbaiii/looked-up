# Phase 0 — Feasibility spike

Measured on 2026-10-07 from a MacBook (Apple Silicon, home connection ≈1.4 MB/s from
dumps.wikimedia.org), Python 3.12, DuckDB 1.5.6. Every number below comes from a script in
[`spike/`](../spike) and can be reproduced; raw downloads live in the git-ignored `data/`.

---

## 1. Hourly pageview dumps

Source: `https://dumps.wikimedia.org/other/pageviews/YYYY/YYYY-MM/pageviews-YYYYMMDD-HH0000.gz`
Script: [`spike/q1_hourly_dumps.py`](../spike/q1_hourly_dumps.py),
[`spike/q1b_compaction.py`](../spike/q1b_compaction.py)

### 1a. Shape, size and lag of the latest three files

| File | Hour covered (UTC) | Posted (UTC) | Lag after hour end | gz | Uncompressed | Lines | Projects |
|---|---|---|---|---|---|---|---|
| pageviews-20261007-080000.gz | 07:00–08:00 | 10:27 | 2 h 27 min | 54.5 MB | 196.0 MB | 6,055,129 | 1,954 |
| pageviews-20261007-090000.gz | 08:00–09:00 | 11:10 | 2 h 10 min | 55.5 MB | 199.3 MB | 6,194,749 | 1,961 |
| pageviews-20261007-100000.gz | 09:00–10:00 | 12:29 | 2 h 29 min | 55.4 MB | 199.5 MB | 6,200,548 | 1,960 |

- **The filename timestamp is the *end* of the hour.** Wikitech says so, and I verified it:
  the `en` + `en.m` total in `…-100000.gz` (6,273,158) equals **exactly** the REST API
  `aggregate/en.wikipedia/all-access/user/hourly` value for hour `2026100709`, the hour *starting* at 09:00.
- That exact match also shows that **the dumps contain `user` traffic only** (spiders and the
  "automated" class are already removed) and that `all-access` (desktop + mobile web + apps) is fully represented.
- **Lag over the last 7 days (168 files):** min 121 min, **median 134 min**, p90 161 min, max 648 min
  after the end of the hour. So with hourly dumps, an event is visible **≈2.2–2.7 h after the hour it
  happens in closes**. Occasional outliers (one at ≈11 h) need a "late file" retry.
- Volume: a full day (2026-10-06) is **1.25 GB gz** across 24 files, ≈ **457 GB/year raw gz**.
  Download of one file took 38–45 s at home.
- The `bytes` column is **always 0** now (0 non-zero rows out of 6.2 M), so we can drop it.
- 1,960 distinct project codes per hour. Wikipedia (`xx` + `xx.m`) carries **91.9 %** of all
  views. **376** Wikipedia languages appear in a single hour, and the **top 50 languages hold 98.9 %** of
  Wikipedia views.

### 1b. DuckDB load and Parquet footprint (one hour = `…-100000.gz`)

- `read_csv(... delim=' ', quote='', escape='')` straight from the `.gz`: **0.7 s** for 6.2 M rows
  (`ignore_errors=true` is needed for a handful of malformed titles).
- Parquet, zstd, sorted by (project, title). Extrapolated with the real day/hour gz ratio (22.6 ×, not 24 ×,
  because 09:00 UTC is a busier-than-average hour):

| Variant | Per hour | Per day | Per year |
|---|---|---|---|
| (i) All projects, `project, page_title, views` | 60.7 MB | 1.37 GB | **≈ 500 GB** |
| (ii) Wikipedia top-50 langs, desktop & mobile rows separate | 45.3 MB | 1.03 GB | ≈ 374 GB |
| (ii) Wikipedia top-50, desktop + mobile **summed** | 42.3 MB | 0.96 GB | ≈ 350 GB |
| (ii) summed, compacted into multi-hour files (zstd 9) | — | ≈ 0.62 GB | **≈ 228 GB** |
| (ii) summed, keep rows with ≥ 2 views/hour | 15.6 MB | 0.35 GB | ≈ 129 GB |

Parquet is barely smaller than gzip at the per-hour level, because the long tail of unique titles
dominates. **Compaction matters**: putting 3 hours in one file sorted by (lang, title, hour) is
34 % smaller than 3 separate files (125.8 MB → 82.9 MB at zstd 9, 75.6 MB at zstd 19), because
titles repeat. A full-day file should do better still. §6 shows how retention thresholds bring this
down to single-digit GB/year.

Top-50 languages by views in that hour (desktop+mobile): en, ja, de, fr, ru, it, zh, es, pl, fa, nl,
tr, pt, ar, sv, id, cs, ko, uk, fi, he, vi, th, hu, el, ro, no, sr, hi, da, bg, ca, ceb, hr, simple,
ms, sk, bn, et, ta, lt, af, sl, hy, kk, te, ka, eu, zh-yue, az. This is a single hour, so the
list is biased to time zones awake at 09:00 UTC (e.g. es and pt rank low). The real list must come
from a full day or week.

### 1c. Mobile (`.m`) vs desktop

- `xx` = desktop site, `xx.m` = mobile web **plus the mobile apps** (the REST `all-access` total matches
  `xx + xx.m` exactly). Careful: `.m` also tags non-Wikipedia sites (`commons.m`, `meta.m`, …), and
  `en.m.d` style codes mean "mobile Wiktionary". Filtering Wikipedia needs `^[a-z0-9-]+(\.m)?$` plus a
  deny-list of non-language prefixes.
- Mobile share of Wikipedia views in the hour: **56 %** overall, with wide variation: fa 88 %, hi 82 %,
  ar 79 %, ja 69 %, en 56 %, de 45 %, fr 45 %, ca 31 %, simple 25 %, and **ceb 0.8 %** (bot-made
  Cebuano articles get almost no human mobile traffic).
- 902 k titles appear on both desktop and mobile in the same hour.
- **Decision: sum them.** Attention is attention. We gain nothing from the split for spike detection,
  summing removes ≈ 17 % of rows (5.33 M → 4.43 M), and the mobile share differs so much by
  language that comparing desktop-only numbers across communities would be misleading. If we ever want
  the split, it is a cheap derived column.

### 1d. `pageview_complete` (daily files) vs hourly dumps

Source: `https://dumps.wikimedia.org/other/pageview_complete/YYYY/YYYY-MM/pageviews-YYYYMMDD-{user,automated}.bz2`
Script: [`spike/q1d_pageview_complete.py`](../spike/q1d_pageview_complete.py)

| | Hourly `pageviews` | Daily `pageview_complete` (user) |
|---|---|---|
| Granularity | 1 file per hour | 1 file per day, **hourly counts encoded inside** (`A3C12` = 3 views at 00h, 12 at 02h) |
| Lag | **≈ 2.2 h after the hour** (median) | 2.3–2.8 h after the **day** ends → up to ≈ 26 h after the first hour |
| Size | 24 × ≈ 52 MB gz ≈ 1.25 GB/day | ≈ 0.69 GB/day bz2 (≈ 3.9 GB uncompressed) |
| Columns | project, title, views, (bytes=0) | wiki, title, **page_id**, access (desktop / mobile-web / mobile-app), daily total, hourly string |
| Agent | user only | separate `user` and `automated` files |
| Compression | gzip (fast to read) | bz2 (≈ 10 × slower to decompress) |
| History | since May 2015 | since 2011 (merged with older pagecounts) |

In a 20,000-line sample the hourly letters always summed to the daily total. The Q5 cross-check below compares
both sources hour by hour.

**Which source:** the **hourly dumps for the live pipeline**, because "right now" is the whole product and
daily files are a day late. **`pageview_complete` for backfill and baselines**: one file per day
instead of 24, half the bytes, `page_id` included (robust against page moves), and the same hourly
resolution. We use both.
