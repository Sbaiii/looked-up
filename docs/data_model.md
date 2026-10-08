# Data model

The lake is a public Hugging Face dataset, **[`Sbaiii/looked-up`](https://huggingface.co/datasets/Sbaiii/looked-up)**,
refreshed every hour by GitHub Actions. Decisions: ADR [0005](adr/0005-separate-desktop-and-mobile-views.md)–[0011](adr/0011-wikidata-sitelinks.md).

## Layout

```
data/
  hourly/year=YYYY/month=MM/day=DD/hour=HH.parquet   one file per UTC hour (zstd)
  wikidata/sitelinks.parquet                         (lang, title) -> Wikidata QID
  manifest.json                                      every hour present, with provenance
```

`HH` is the **start** of the hour. The source dumps name files after the *end* of the hour
(`pageviews-20261007-120000.gz` = 11:00–12:00 UTC), so `ts_hour_start = file timestamp − 1 h`.
This was verified against the REST API (ADR 0008).

## `data/hourly/…/hour=HH.parquet`

| Column | Type | Meaning |
|---|---|---|
| `ts_hour_start` | `TIMESTAMP` | Start of the hour, **UTC** (stored without time zone) |
| `lang` | `VARCHAR` | Wikipedia language code (`en`, `fr`, `zh`, …), see `config/languages.yml` |
| `title` | `VARCHAR` | Article title as in URLs: underscores, percent-decoding applied once |
| `views_desktop` | `INTEGER` | Desktop views (`xx` in the hourly dumps) |
| `views_mobile` | `INTEGER` | Mobile web + app views (`xx.m`) |

- Rows are sorted by `(lang, title)`. Each `(ts_hour_start, lang, title)` appears once.
- Only `user` traffic is included (Wikimedia already removes spiders and the `automated` class). Some bots still get through.
  `views_mobile / (views_desktop + views_mobile)` is the first signal to check (humans ≈ 56 % mobile, bots ≈ 0 %).
- Desktop and mobile are **never pre-summed** (ADR 0005).

### Retention (ADR 0007)

A row is kept when all of these hold:

1. `lang` is one of the **active languages** (`top_n` first entries of `config/languages.yml`, 30 in v1);
2. the title is an **article**. Excluded are: the main page (localised, plus `Main_Page`); titles whose prefix is a
   namespace of that wiki (localised names and aliases from siteinfo, in `config/namespaces.json`, plus the canonical
   English names); and the `-` title;
3. `views_desktop + views_mobile >= 5` in that hour.

A missing row means **fewer than 5 views** in that hour, not zero. Raw dumps are not kept. Wikimedia keeps them
(CC0, since 2015), so any hour can be rebuilt with other rules.

### Size

Measured on 7 Oct 2026 (four hours, 07:00–11:00 UTC): **440 k–530 k rows and 4.3–5.2 MB per hour**, so about
110 MB a day and **≈ 40 GB a year**. The one-file-per-hour layout costs about 2.5× the daily compacted files
measured in Phase 0, because Parquet cannot compress repeated titles across hours. If storage becomes a concern,
compact closed months into one file per day (same schema). That is a Phase 2 option, not needed for Hugging Face today.

## `data/wikidata/sitelinks.parquet`

| Column | Type | Meaning |
|---|---|---|
| `lang` | `VARCHAR` | Same codes as the hourly files |
| `title` | `VARCHAR` | Sitelink title with underscores (joins on `hourly.title`) |
| `qid` | `INTEGER` | Numeric Wikidata id: `597` means `Q597` |

Built from `wikidatawiki-latest-wb_items_per_site.sql.gz` for the active languages, sorted by `(lang, title)`, and
refreshed monthly. Redirects and articles newer than the dump don't match. Coverage is in
[wikidata_coverage.md](wikidata_coverage.md).

## `data/manifest.json`

```json
{
  "schema_version": 1,
  "updated_at": "2026-10-08T14:46:02Z",
  "hour_count": 2160,
  "hours": {
    "2026-10-07T11:00:00Z": {
      "path": "data/hourly/year=2026/month=10/day=07/hour=11.parquet",
      "rows": 412345, "bytes": 1834567,
      "source": "hourly_dump",
      "ingested_at": "2026-10-07T14:46:01Z"
    }
  }
}
```

- `source` is `hourly_dump` (live path) or `pageview_complete` (backfill). Both paths share one transformation.
  For the same hour they agree on ≈ 99.999 % of rows. `pageview_complete` misses a few mobile views on missing
  pages and redirects (≈ 0.0003 % of views, ADR 0010). Check with `python -m lookedup.cli validate`.
- An hour is present **if and only if** it is in the manifest. Writers commit the data files and the manifest in a
  single Hub commit.

## Query it from DuckDB (5 lines)

```python
import duckdb
con = duckdb.connect(); con.execute("INSTALL httpfs; LOAD httpfs;")
lake = "hf://datasets/Sbaiii/looked-up/data/hourly/*/*/*/*.parquet"
con.sql(f"""SELECT title, sum(views_desktop + views_mobile) AS views FROM read_parquet('{lake}')
            WHERE lang = 'fr' AND ts_hour_start >= (now() AT TIME ZONE 'UTC') - INTERVAL 24 HOUR GROUP BY 1 ORDER BY 2 DESC LIMIT 20""").show()
```

Reading one file is faster than globbing the whole lake:

```bash
python -m lookedup.cli top --lang fr --hour 2026-10-06T14:00     # top 20 with desktop, mobile, mobile share
```

To join with Wikidata: `JOIN read_parquet('hf://datasets/Sbaiii/looked-up/data/wikidata/sitelinks.parquet') USING (lang, title)`.
