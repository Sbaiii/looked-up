---
license: cc0-1.0
pretty_name: "Looked Up: hourly Wikipedia attention across 30 languages"
language: [en, ja, de, ru, fr, es, it, zh, pt, pl, fa, nl, ar, tr, id, sv, ko, cs, fi, uk, he, vi, hu, el, th, ro, "no", sr, bg, hi]
multilinguality: multilingual
size_categories: [1B<n<10B]
task_categories: [time-series-forecasting]
tags: [wikipedia, pageviews, attention, time-series, wikidata, multilingual]
configs:
  - config_name: hourly
    data_files: "data/hourly/*/*/*.parquet"
    default: true
  - config_name: sitelinks
    data_files: "data/wikidata/sitelinks.parquet"
---

# Looked Up: hourly Wikipedia attention across 30 languages

**What the world pays attention to, hour by hour, across languages.** This dataset holds the hourly pageviews of
every Wikipedia **article** in the 30 most-read language editions. It is refreshed every hour from Wikimedia's public
pageview dumps, with desktop and mobile views kept apart and every title mappable to a Wikidata item.

Built and maintained by [github.com/Sbaiii/looked-up](https://github.com/Sbaiii/looked-up), where the code,
the [data model](https://github.com/Sbaiii/looked-up/blob/main/docs/data_model.md) and all design decisions
([ADRs](https://github.com/Sbaiii/looked-up/tree/main/docs/adr)) live.

## Quick start (DuckDB)

```python
import duckdb
con = duckdb.connect(); con.execute("INSTALL httpfs; LOAD httpfs;")
lake = "hf://datasets/Sbaiiiiii/looked-up/data/hourly/*/*/*.parquet"
con.sql(f"""SELECT title, sum(views_desktop + views_mobile) AS views FROM read_parquet('{lake}')
            WHERE lang = 'fr' AND ts_hour_start >= (now() AT TIME ZONE 'UTC') - INTERVAL 24 HOUR GROUP BY 1 ORDER BY 2 DESC LIMIT 20""").show()
```

One day is one file, so reading a single day is fastest:
`read_parquet('hf://datasets/Sbaiiiiii/looked-up/data/hourly/year=2026/month=10/day=06.parquet')`.

## Layout

```
data/hourly/year=YYYY/month=MM/day=DD.parquet   all ingested hours of one UTC day
data/wikidata/sitelinks.parquet                 (lang, title) -> Wikidata QID
data/manifest.json                              every hour present, with row count, source and ingestion time
```

## Schema

`data/hourly/…/day=DD.parquet`, with rows sorted by `(lang, title, ts_hour_start)`, zstd level 9:

| Column | Type | Meaning |
|---|---|---|
| `ts_hour_start` | `TIMESTAMP` | Start of the hour, **UTC** (stored without a time zone) |
| `lang` | `VARCHAR` | Wikipedia language code |
| `title` | `VARCHAR` | Article title as in URLs (underscores, percent-decoded once) |
| `views_desktop` | `INTEGER` | Desktop views |
| `views_mobile` | `INTEGER` | Mobile web + mobile app views |

`data/wikidata/sitelinks.parquet` has `lang VARCHAR`, `title VARCHAR` and `qid INTEGER` (597 means
[Q597](https://www.wikidata.org/wiki/Q597)). Join on `(lang, title)`. About 98.6 % of retained views match a QID.

## What is kept (retention)

A row is kept when the title is an **article** and `views_desktop + views_mobile >= 5` in that hour. Excluded are the
main page, namespace pages (Special:, Talk:, File:, User:, Category:, Template:, Help:, Portal:, Draft:, Wikipedia:,
… in each wiki's own language, taken from its siteinfo) and the `-` title.

**A missing row means fewer than 5 views that hour, not zero.** Only `user` traffic is included: Wikimedia
already removes spiders and traffic it classifies as automated.

## Why desktop and mobile are separate columns

Humans read Wikipedia mostly on phones (≈ 56–90 % mobile, depending on the language). Bot traffic that passes
Wikimedia's filters is almost all desktop. The mobile share is therefore a strong human-vs-bot signal.
For example, `fr:Cookie_(informatique)` gets tens of thousands of views per hour at 0.6 % mobile, while the human
articles around it are 60–93 % mobile. Sum the two columns for total attention, or compare them to filter automation.

## Languages

The 30 Wikipedias with the most **human article views** over 1–7 Oct 2026. The ranking excludes namespace pages,
main pages and titles with > 1,000 views and < 5 % mobile.
[config/languages.yml](https://github.com/Sbaiii/looked-up/blob/main/config/languages.yml) has the full ranking of 60.

| Rank | Code | Language | Native name | Human article views/day | Mobile share |
|---|---|---|---|---|---|
| 1 | `en` | English | English | 191.2 M | 66 % |
| 2 | `ja` | Japanese | 日本語 | 26.5 M | 70 % |
| 3 | `de` | German | Deutsch | 20.1 M | 66 % |
| 4 | `ru` | Russian | русский | 15.8 M | 70 % |
| 5 | `fr` | French | français | 15.7 M | 67 % |
| 6 | `es` | Spanish | español | 13.8 M | 75 % |
| 7 | `it` | Italian | italiano | 10.5 M | 76 % |
| 8 | `zh` | Chinese | 中文 | 8.6 M | 60 % |
| 9 | `pt` | Portuguese | português | 5.4 M | 72 % |
| 10 | `pl` | Polish | polski | 5.0 M | 68 % |
| 11 | `fa` | Persian | فارسی | 4.7 M | 91 % |
| 12 | `nl` | Dutch | Nederlands | 2.8 M | 64 % |
| 13 | `ar` | Arabic | العربية | 2.7 M | 82 % |
| 14 | `tr` | Turkish | Türkçe | 2.5 M | 77 % |
| 15 | `id` | Indonesian | Bahasa Indonesia | 1.8 M | 82 % |
| 16 | `sv` | Swedish | svenska | 1.8 M | 68 % |
| 17 | `ko` | Korean | 한국어 | 1.6 M | 67 % |
| 18 | `cs` | Czech | čeština | 1.5 M | 64 % |
| 19 | `fi` | Finnish | suomi | 1.4 M | 68 % |
| 20 | `uk` | Ukrainian | українська | 1.3 M | 68 % |
| 21 | `he` | Hebrew | עברית | 1.3 M | 76 % |
| 22 | `vi` | Vietnamese | Tiếng Việt | 1.2 M | 63 % |
| 23 | `hu` | Hungarian | magyar | 1.0 M | 68 % |
| 24 | `el` | Greek | Ελληνικά | 0.8 M | 71 % |
| 25 | `th` | Thai | ไทย | 0.8 M | 64 % |
| 26 | `ro` | Romanian | română | 0.7 M | 66 % |
| 27 | `no` | Norwegian | norsk | 0.6 M | 61 % |
| 28 | `sr` | Serbian | српски / srpski | 0.6 M | 62 % |
| 29 | `bg` | Bulgarian | български | 0.5 M | 69 % |
| 30 | `hi` | Hindi | हिन्दी | 0.5 M | 86 % |

## Attention events (derived)

Every hour, new hours are also scored for **attention events**: one entity spiking in at least 3 languages within
6 hours, measured against its own 28-day baseline. The spike files, event files and `data/latest.json` (last 24 h,
top 50, labels in the 30 languages) are described in the
[data model](https://github.com/Sbaiii/looked-up/blob/main/docs/data_model.md#scoring-outputs-phase-2-adr-0014).
The definitions were pre-registered and evaluated honestly; the
[Phase 2 results](https://github.com/Sbaiii/looked-up/blob/main/docs/analysis/phase2_results.md) report what the
detector does and doesn't capture.

## Update frequency and provenance

- **Hourly.** A GitHub Actions job runs at :45 every hour and ingests every published hour of the last 72 h that is
  still missing. Wikimedia publishes each hourly dump ≈ 2 h 15 min (median) after the hour ends, so the newest hour
  is usually 2–3 h old.
- **History** is backfilled from Wikimedia's daily `pageview_complete` files (`source = pageview_complete` in the
  manifest). Live hours come from the hourly dumps (`source = hourly_dump`).
- **Known caveat:** for the same hour, the two sources agree on ≈ 99.999 % of rows. `pageview_complete` misses
  a few mobile views, mostly on pages that do not exist or are redirects, worth about 0.0003 % of views.

## Source and license

Derived from the [Wikimedia pageview dumps](https://dumps.wikimedia.org/other/pageviews/) and
[pageview_complete](https://dumps.wikimedia.org/other/pageview_complete/), and from Wikidata's `wb_items_per_site`
table. All are released under [CC0](https://creativecommons.org/publicdomain/zero/1.0/) by the Wikimedia Foundation.
This dataset is also CC0.

Titles are kept exactly as Wikimedia reports them: no redirect resolution and no moderation of article names.
