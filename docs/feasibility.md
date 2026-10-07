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
titles repeat. **A real full day does much better:** the 24 hourly files of 2026-08-28 total 1.00 GB and compact
into **one 361 MB day file (ratio 0.36), ≈ 132 GB/year** ([`q6c`](../spike/q6c_full_day_compaction.py)).
§6 shows how a retention threshold brings this down to ≈ 15–20 GB/year.

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
| Compression | gzip: a day (24 files, 147.7 M lines) streams in **50 s** | bz2: a day (55.5 M lines, 3.52 GB) streams in **84 s**, single-threaded Python |
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

---

## 4. Entity unification (Wikidata)

Scripts: [`spike/q4_wikidata.py`](../spike/q4_wikidata.py), [`spike/q4b_join_coverage.py`](../spike/q4b_join_coverage.py)

### API: one QID, every language

`action=wbgetentities&sites=enwiki&titles=Lisbon&props=sitelinks` → **Q597**, with 267 sitelinks, 224 of them
Wikipedias: en *Lisbon*, pt *Lisboa*, fr *Lisbonne*, ja *リスボン*, ar *لشبونة*, ru *Лиссабон*, zh *里斯本*,
hi *लिस्बन*, … The API works well for a handful of entities, but it's the wrong tool for mapping 6 M pageview rows an hour.

### Offline: `wikidatawiki-latest-wb_items_per_site.sql.gz`

- **Size: 1.91 GB gz** (dump of 2026-10-03), so under 3 GB and downloaded in full. It parsed in **6.2 min** with a
  streaming regex in pure Python. It comes from the **monthly** dump run (2026-10-01 run, file written 2026-10-03), so the mapping can be up to ~5 weeks stale. New event articles always need a live fallback (API or the `page-create` stream).
- Structure (the CREATE TABLE in the dump):

  ```sql
  CREATE TABLE `wb_items_per_site` (
    `ips_row_id`    bigint unsigned NOT NULL AUTO_INCREMENT,
    `ips_item_id`   int unsigned NOT NULL,        -- the Q number (597 = Q597)
    `ips_site_id`   varbinary(32) NOT NULL,       -- 'enwiki', 'ptwiki', 'zh_yuewiki', 'commonswiki', ...
    `ips_site_page` varbinary(310) NOT NULL,      -- title with spaces, e.g. 'Lisbon'
    UNIQUE KEY (`ips_site_id`, `ips_site_page`), KEY (`ips_item_id`)
  )
  ```
  Rows look like `(55,3596065,'abwiki','Џьгьарда')`. mariadb-dump 10.11 writes **one tuple per line**, so a line
  parser works without a SQL engine.
- **100.6 M sitelinks, 959 sites, 366 Wikipedias.** Biggest: enwiki 10.4 M, commonswiki 6.2 M, cebwiki 5.7 M,
  dewiki 3.8 M, frwiki 3.5 M.
- For our top-50 languages: **70.1 M (site, title) → QID rows covering 27.9 M distinct items**, which is 1.2 GB of
  Parquet unsorted. We can shrink it a lot by keeping only titles that actually get views.

**Yes, it is exactly the mapping we need.** It goes (site, title) → QID, and the unique key guarantees that a title maps
to at most one item. Two adjustments: dump titles use spaces where pageviews use underscores, and
`zh-yue` becomes `zh_yuewiki`.

### How much traffic actually joins?

Joining one hour of top-50 Wikipedia pageviews (desktop + mobile summed) on `(site, title)`:

- **93.4 % of views** (87.0 % of rows) get a QID. Excluding namespace-prefixed titles: **95.5 %**.
- 2.44 M distinct QIDs see at least one view in a single hour.
- Per language: ja 96.9 %, pl 96.4 %, fr 94.5 %, it 94.5 %, ru 94.1 %, de 93.5 %, en 93.2 %, zh **87.9 %**.
- What doesn't match: `Special:Search` in every language (the biggest bucket), `-` (bad requests), `File:` pages,
  **redirects** (pageviews count the requested title, not the target), and articles created after the
  2026-10-03 dump (e.g. *2026_Rolex_Shanghai_Masters_–_Singles*). zh is lower because of script-variant titles.
- **Redirect resolution is needed** for anything event-driven. New articles get renamed in their first hours,
  and the old names keep collecting views. Sources: the `redirect` + `page` table dumps per wiki, or
  `pageview_complete`'s `page_id` (which survives renames). Q5 resolves redirects through the API, and that
  was necessary to get correct numbers.

---

## 5. The key test: do spikes precede the news?

Scripts: [`q5a_current_events.py`](../spike/q5a_current_events.py) (pick events),
[`q5_spike_test.py`](../spike/q5_spike_test.py) (build tables), [`q5b_analyse.py`](../spike/q5b_analyse.py)
(detectors), [`q5c_edit_lead.py`](../spike/q5c_edit_lead.py) (editor reaction).
Tables: [`q5_harald_v_death_hourly.csv`](q5_harald_v_death_hourly.csv),
[`q5_colombia_earthquake_hourly.csv`](q5_colombia_earthquake_hourly.csv),
[`q5_us_open_final_zverev_hourly.csv`](q5_us_open_final_zverev_hourly.csv),
[`q5_detection_summary.csv`](q5_detection_summary.csv), [`q5_edit_lead.csv`](q5_edit_lead.csv).

### Method

- 3 events from Portal:Current_events in the last 60 days: a death, a disaster and a sports final.
- **24 hourly dump files per event** (the cap), titles resolved through Wikidata in **10 languages each**, with **every
  redirect summed in**. New articles get renamed, and views land on whatever title was live at the time.
- Baseline "same hour of the previous day" comes from the previous day's **`pageview_complete`** file (hourly
  counts inside), so we didn't need 24 more hourly files. **Cross-check: on the 179 (hour, title) pairs present in both
  sources, the hourly dumps and `pageview_complete` are identical, 179/179.** The sources agree exactly, and the
  "filename = end of hour" reading is confirmed again.
- Detectors (first hour from event − 6 h onward, floor ≥ 20 views):
  - **day-over-day (as specified):** views ≥ 5 × same hour of the previous day;
  - **hour-over-hour (added):** views ≥ 3 × median of the previous 3 hours.

### Events and real timestamps (UTC)

| Event | Real time | Source |
|---|---|---|
| Death of King Harald V of Norway | died **04:35**, palace announcement **06:35** (28 Aug) | en.wikipedia *Death and state funeral of Harald V* (06:35 / 08:35 CEST) |
| M7.4 earthquake, Chocó, Colombia | **12:34:28** (10 Aug) | article infobox (USGS-style timestamp, 07:34 COT) |
| US Open men's final, Zverev d. Shelton | start **18:00**, result **≈ 21:48** (13 Sep) | start: Al Jazeera (2 p.m. ET). End: de.wikipedia edit at 21:49 *"er hat vor 20 Sekunden die us open gewonnen"*; first wire 21:55 |

### Results

**Harald V: the whole of Europe in the same hour.** Views of *Harald V* per hour:

| Lang | 03:00 | 04:00 | 05:00 | **06:00** | 07:00 | jump 05→06 |
|---|---|---|---|---|---|---|
| en | 2,461 | 2,586 | 2,881 | **20,949** | 53,428 | 7.3 × |
| no | 216 | 510 | 812 | **6,082** | 9,419 | 7.5 × |
| sv | 351 | 864 | 1,523 | **5,967** | 8,313 | 3.9 × |
| da | 152 | 277 | 414 | **2,002** | 3,515 | 4.8 × |
| de | 521 | 922 | 1,387 | **10,015** | 21,585 | 7.2 × |
| fr | 167 | 375 | 537 | **4,272** | 11,248 | 8.0 × |
| es | 313 | 331 | 386 | **2,663** | 5,697 | 6.9 × |
| it | 105 | 174 | 338 | **2,615** | 8,217 | 7.7 × |
| ru | 83 | 113 | 170 | **3,643** | 8,096 | 21.4 × |
| ja | 98 | 86 | 97 | 201 | **2,658** | 13 × at 07:00 |

- **9 of 10 languages jump in the 06:00–07:00 hour**, the hour of the 06:35 announcement. ja follows one hour
  later (16:00 JST). Detection delay is **within the announcement hour (< 25 min after the announcement)**.
- **The specified day-over-day rule fails here:** it fires at 00:00 in all 10 languages, 4.6 h *before* the
  death. On 27 Aug the palace said his condition was "extremely serious", so the previous day was already a news
  day (en baseline went from ~110/h to 6.6 k/h). Comparing to yesterday's same hour assumes yesterday was quiet.
- The 04:00–05:00 rise in no/sv/de (2–3 × the earlier hours, before the official announcement) is **ambiguous**:
  that hour is 06:00 CEST, the start of the European morning, and the baseline day shows a similar morning ramp. I
  don't count it as a "before the news" signal.

**Colombia earthquake: the local language reacts first, within the hour.**

| Article | Lang | First spike hour (UTC) | Delay after quake | Views in that hour (prev-day same hour) |
|---|---|---|---|---|
| *Chocó Department* (existing) | **es** | **12:00–13:00** | **≤ 26 min** | 376 (4), then 1,492 at 13:00 |
| | en | 12:00–13:00 | ≤ 26 min | 61 (6) |
| | fr, pt, it | 13:00 | + 0.4 h | 43–114 |
| | de, ja | 14:00 | + 1.4 h | 47–102 |
| | zh | 15:00 | + 2.4 h | 21 |
| | ru, ar | none | — | ≤ 11 |
| *2026 Colombia earthquake* (new) | en | 13:00 | created **12:49** (+16 min), 855 views at 13:00 | — |
| | es | 13:00 | created 13:09 (+36 min) | — |
| | pt, zh, ar, ja | 14:00–16:00 | created + 2 to 4 h | — |
| | fr, it / de / ru | — | created + 8 h / + 22 h / + 2 days | — |

- Attention spreads from the local language outward: es/en → fr/pt/it (+1 h) → de/ja (+2 h) → zh (+3 h).
  That makes it a good product feature to show.
- An existing, related article (the region) is the fastest and most reliable signal. The event's own article
  doesn't exist yet in most languages for hours, so **it has no QID yet**.

**US Open final: scheduled events spike at kick-off, not at the result.**

- 8 of 10 languages flagged in the **18:00 hour (match start)**, es at 17:00 (pre-match) and ja at 19:00. That is
  3.8 h *before* the result. en climbs 7 k → 41 k → 49 k → 58 k → 89 k → **119.6 k in the 22:00 hour**, which holds
  the 21:48 result.
- **de gets a second wave at 03:00–06:00 UTC** the next morning (Germans waking up to the news: 43 × baseline
  at 04:00). Attention follows time zones, so hourly granularity really matters.
- Both detectors agree here because the previous day was quiet.

### Editors are faster than readers (and faster than the dumps)

First edit or creation after the event ([`q5_edit_lead.csv`](q5_edit_lead.csv)):

- Zverev: **all 10 languages edited within 1–29 min** of the result (de at +1 min, it +3, pt +5, es +6, fr +7, ru +9,
  ja +11, pl +24, zh +29).
- Harald V: death-related edits in no/da/fr/es/ru at 06:39–06:43 (**4–8 min after the announcement**), ja at 07:03.
  (Earlier edits that morning were routine: a comma, link clean-up.)
- Quake: en article **created 16 min after the quake**, es 36 min.

### Answer

- **Pageview spikes do not precede the news. They coincide with it**, inside the same clock hour, for
  unscheduled events (≤ 25–30 min after the first public information), and they appear in **many languages at
  once** (Harald: 9/10 in one hour; US Open: 8/10 in one hour; quake: 2 at once, 7 within 3 h).
- **Detection delay for us with hourly dumps:** hour end + median 2.2 h publication → **≈ 2.5–3.5 h after the
  event**. Daily data (top lists, `pageview_complete`) only arrives 2.4 h after the UTC day ends, so hourly dumps are **≈ 12–23 h faster** depending on the time of day. They are still 2–3 h *slower* than the newswire.
- **The edit stream is the only signal that comes before the dumps**: editors react within 1–30 min. A
  burst of human edits (or a new article) linked to a QID is the "early warning". Pageviews confirm the attention and measure its size.
- Detection design: **the specified rule (5 × same hour yesterday) works for "quiet before" events and fails
  after a newsy day.** Use a trailing baseline (previous hours plus a 7-day same-hour median), a views floor, and
  multi-language confirmation.
- Where Looked Up adds value is not beating the news. It is **measuring how much attention the world pays, in which
  languages, how it spreads and how long it lasts**, at hourly resolution.

