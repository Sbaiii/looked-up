# Data model

The lake is a public Hugging Face dataset, **[`Sbaiiiiii/looked-up`](https://huggingface.co/datasets/Sbaiiiiii/looked-up)**,
refreshed every hour by GitHub Actions. Decisions: ADR [0005](adr/0005-separate-desktop-and-mobile-views.md)–[0012](adr/0012-one-parquet-file-per-day.md).

## Layout

```
data/
  hourly/year=YYYY/month=MM/day=DD.parquet          all ingested hours of one UTC day (zstd 9)
  wikidata/sitelinks.parquet                         (lang, title) -> Wikidata QID
  manifest.json                                      every hour present, with provenance
```

`ts_hour_start` is the **start** of the hour. The source dumps name files after the *end* of the hour
(`pageviews-20261007-120000.gz` = 11:00–12:00 UTC), so `ts_hour_start = file timestamp − 1 h`.
This was verified against the REST API (ADR 0008).

## `data/hourly/…/day=DD.parquet`

| Column | Type | Meaning |
|---|---|---|
| `ts_hour_start` | `TIMESTAMP` | Start of the hour, **UTC** (stored without time zone) |
| `lang` | `VARCHAR` | Wikipedia language code (`en`, `fr`, `zh`, …), see `config/languages.yml` |
| `title` | `VARCHAR` | Article title as in URLs: underscores, percent-decoding applied once |
| `views_desktop` | `INTEGER` | Desktop views (`xx` in the hourly dumps) |
| `views_mobile` | `INTEGER` | Mobile web + app views (`xx.m`) |

- One file per UTC day (ADR 0012). Rows are sorted by `(lang, title, ts_hour_start)`, in row groups of ≈ 1 M rows.
  Each `(ts_hour_start, lang, title)` appears once. A day file can be partial (today, or a gap); the manifest says
  which hours exist.
- Adding an hour rewrites that day's file (read, replace the hour's rows, sort, write). All writers share
  `lookedup.store.write_hours`, which retries the whole merge if another writer committed meanwhile.
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

Measured on 2026-10-08 over 6 full days (1–6 Oct): **≈ 12.5 M rows and 44.4 MB per day**, so **≈ 16 GB a year**
for 30 languages. The Phase 1 layout of one file per hour needed 120 MB/day (≈ 44 GB/year). Daily files are 0.37×
that because titles repeat across the hours of a day (ADR 0012).

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
  "schema_version": 2,
  "updated_at": "2026-10-08T14:46:02Z",
  "hour_count": 2160,
  "total_bytes": 4012345678,
  "files": {
    "data/hourly/year=2026/month=10/day=07.parquet": {"rows": 12512345, "bytes": 44438296, "updated_at": "2026-10-08T02:46:01Z"}
  },
  "hours": {
    "2026-10-07T11:00:00Z": {
      "path": "data/hourly/year=2026/month=10/day=07.parquet",
      "rows": 528990,
      "source": "hourly_dump",
      "ingested_at": "2026-10-07T14:46:01Z"
    }
  }
}
```

- The manifest tracks **hours**. An hour is present **if and only if** it is in `hours`. `files` records the size of
  each day file. Writers commit the day files and the manifest in a single Hub commit.
- `source` is `hourly_dump` (live path) or `pageview_complete` (backfill). Both share one transformation.

## Known caveats

- **Backfill vs live hours.** For the same hour, `pageview_complete` (backfill) and the hourly dumps (live) agree on
  ≈ **99.999 % of rows**. Total views differ by ≈ **0.0003 %**. The differing rows are low-volume mobile views on
  pages that do not exist or are redirects, which `pageview_complete` appears to under-count (ADR 0010). Check with
  `python -m lookedup.cli validate`.
- **Absent means < 5.** A missing (hour, lang, title) row means fewer than 5 views, not zero (ADR 0007).
- **Bots inside `user` traffic.** Use the mobile share to spot them (ADR 0005).
- **Redirects are not resolved.** Views count the requested title. Redirect titles do not join to Wikidata.

## Query it from DuckDB (5 lines)

```python
import duckdb
con = duckdb.connect(); con.execute("INSTALL httpfs; LOAD httpfs;")
lake = "hf://datasets/Sbaiiiiii/looked-up/data/hourly/*/*/*.parquet"
con.sql(f"""SELECT title, sum(views_desktop + views_mobile) AS views FROM read_parquet('{lake}')
            WHERE lang = 'fr' AND ts_hour_start >= (now() AT TIME ZONE 'UTC') - INTERVAL 24 HOUR GROUP BY 1 ORDER BY 2 DESC LIMIT 20""").show()
```

Reading one day file is faster than globbing the whole lake:

```bash
python -m lookedup.cli top --lang fr --hour 2026-10-06T14:00     # top 20 with desktop, mobile, mobile share
```

To join with Wikidata: `JOIN read_parquet('hf://datasets/Sbaiiiiii/looked-up/data/wikidata/sitelinks.parquet') USING (lang, title)`.
