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
| Compression | gzip (fast to read) | bz2 (slow to decompress; see Q5 timing) |
| History | since May 2015 | directory listing from 2011; readme says Dec 2007 onward (older years rebuilt from pagecounts); page IDs from 2015 |

Known issue (readme): rows without a page ID have 5 columns instead of 6.
In a 20,000-line sample the hourly letters always summed to the daily total. The Q5 cross-check below compares
both sources hour by hour.

**Which source:** the **hourly dumps for the live pipeline**, because "right now" is the whole product and
daily files are a day late. **`pageview_complete` for backfill and baselines**: one file per day
instead of 24, half the bytes, `page_id` included (robust against page moves), and the same hourly
resolution. We use both.

---

## 2. Pageviews REST API

Base: `https://wikimedia.org/api/rest_v1/metrics/pageviews/` · Script: [`spike/q2_rest_api.py`](../spike/q2_rest_api.py)

### 2a. Top articles for yesterday (2026-10-06, all-access, user)

| | #1–#3 (housekeeping pages) | First real articles |
|---|---|---|
| en | Main_Page 6.45 M, Special:Search 0.90 M, Wikipedia:Featured_pictures 0.58 M | Steve_Gleason 516 k, Christa_Pike 294 k, Jeffrey_Archer 285 k, Jim_Bakker 251 k |
| fr | **Cookie_(informatique) 624 k**, Accueil_principal 510 k, Spécial:Recherche 79 k | Michael_Olise 44 k, Paul_St-Pierre_Plamondon 41 k, Élections_générales_québécoises_de_2026 31 k |
| ja | メインページ 711 k, 特別:検索 110 k | 簗和生 110 k, 玉城ティナ 103 k, 和田邦坊 80 k |
| ar | الصفحة_الرئيسة 34 k | همام_الهمامي 23 k, كأس_الخليج_العربي 21 k, a *File:* page 12 k |

- Each call returns up to 1,000 articles in 30–140 ms. Responses are CDN-cached (`cache-control: s-maxage=14400`).
  Yesterday is available; **today returns 404**. Daily top lists come out once a day, so they cannot
  power "right now".
- **Noise is real even in `user` traffic.** fr's #1 article (`Cookie_(informatique)`, 624 k, more than the Main
  Page) and en's `Wikipedia:Featured_pictures` are almost certainly automated traffic that got through the
  classifier. We need namespace filters (Special:, Wikipedia:, File:/ملف:, Main Page in each language)
  and a single-access/single-title anomaly filter before anything goes on a globe.
- **Rate limits:** the Analytics API docs say limits "are dependent on the client's identity" and
  ask clients to "wait for each request to finish before sending another request". The global Wikimedia
  API policy (mediawiki.org *Wikimedia APIs/Rate limits*) gives **200 requests/minute for
  unauthenticated bots with a compliant User-Agent**, and **10 requests/minute** for requests identified only by IP.
  So the API is fine for spot lookups and impossible for bulk use. **Bulk data must come from dumps.**

### 2b. One article, five languages, 90 days

Wikidata Q90 (Paris), titles resolved through sitelinks: en *Paris*, fr *Paris*, ja *パリ*, ar *باريس*, de *Paris*.

| Lang | Days returned | Views in 90 days (2026-07-09 → 2026-10-06) | Earliest day available |
|---|---|---|---|
| en | 90 | 467,905 | 2015-07-01 |
| fr | 90 | 237,471 | 2015-07-01 |
| de | 90 | 93,320 | 2015-07-01 |
| ja | 90 | 26,565 | 2015-07-01 |
| ar | 90 | 10,848 | 2015-07-01 |

- **Earliest date: 2015-07-01** for per-article data, for every language.
- Per-article granularity is **daily or monthly only**. `hourly` returns HTTP 400 ("granularity should be
  equal to one of the allowed values: [daily, monthly]"). Hourly totals exist only at project level (`aggregate`).

### 2c. Geography: does it exist?

Yes, but coarse, daily at best, and with gaps on purpose.

| Endpoint | Returns | Granularity |
|---|---|---|
| `top-by-country/{project}/{access}/{yyyy}/{mm}` | Countries ranked by views of one project, **bucketed** (`"views": "100000000-999999999"`, plus a rounded `views_ceil`) | monthly |
| `top-per-country/{CC}/{access}/{yyyy}/{mm}/{dd}` | Top ≈ 1,000 articles **across all projects** viewed from one country, `views_ceil` rounded (e.g. 261,500) | daily |

- Example: from France on 2026-10-06, #4 = *Michael_Olise* (fr) 37.6 k and #5 = *Mort_de_Thomas_Perotto* 21.1 k. From
  Japan, #2 = *簗和生* 108.6 k. en.wikipedia by country in September: US ≈ 2.66 B, GB ≈ 0.69 B, IN ≈ 0.49 B.
- `top-per-country` starts in **2021** (2021-01-01 works, 2020-12-31 → 404). Today → 404, so lag ≥ 1 day.
- **Privacy protection list:** 18 of the 38 countries probed return 404 every time, namely RU, TR, IR, EG, SA, AE, CN, HK,
  VN, PK, BD, PS, SY, IQ, CU, VE, BY, KP. The docs also drop countries with ≤ 100 views and zero values.
- **Implication:** there is **no per-article × country × hour data**. A "live globe" has to map attention by
  **language** (and the countries where that language is spoken), plus at most a daily per-country overlay
  that leaves out much of the Middle East, Russia and China. This is a product constraint to design around.

---

## 3. Live edit stream (EventStreams, SSE)

Script: [`spike/q3_edit_stream.py`](../spike/q3_edit_stream.py) · samples in `data/raw/stream/*.jsonl`

| Stream | Duration | Events | Events/s | Sample size |
|---|---|---|---|---|
| `recentchange` | 60 s | 1,790 | **29.8** | 2.4 MB (≈ 3.5 GB/day raw JSON) |
| `page-create` | 20 s | 20 | 1.0 | 32 KB |
| `revision-create` | 20 s | 382 | 19.0 | 624 KB |

`recentchange` breakdown (60 s):

- **Top wikis:** commonswiki 691, wikidatawiki 458, enwiki 166, zhwiki 47, eswiki 32, frwiki 28, ruwiki 27,
  eowiktionary 27, arwiki 21, dewiki 20.
- **Types:** edit 1,036 (58 %), categorize 629 (35 %), log 82 (5 %), new 43 (2 %).
- **Bot fraction: 30.9 %.** Wikipedia sites are only **28.8 %** of events, and **human edits/new pages on Wikipedias
  ≈ 4.3/s**. Main namespace (ns 0) is 42.7 % of all events.
- Delivery lag (event `timestamp` → receipt): median 34 s, p95 59 s. Part of this is the stream replaying recent
  history on connect, so true steady-state lag is lower.
- `page-create` / `revision-create` carry `page_id`, `rev_id`, `performer`, `rev_len`, but **no
  `bot` flag at the top level** (it sits in `performer.user_is_bot`). `revision-create` is dominated by Wikidata and Commons
  just like `recentchange`.

**Takeaway:** the edit stream is a cheap, sub-minute signal (one SSE connection, ≈ 30 msgs/s), but it is
**noisy and sparse per article**. Most of it is Commons/Wikidata/bots. It can't measure attention on
its own. Its value is as an **early-warning hint**: a burst of human edits to one article in several
languages, or a brand-new article, shows up ≈ 2–3 h before the hourly pageview dump confirms the
attention. It needs a long-running consumer, which GitHub Actions doesn't provide (see §6). It is a
"later" feature.
