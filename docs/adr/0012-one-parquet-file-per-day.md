# 0012 — One Parquet file per day

- Status: accepted. Supersedes the "one file per hour" layout of ADR 0008. Schema, retention and manifest semantics are unchanged.
- Date: 2026-10-08

## Context

Phase 1 stored one Parquet file per hour (≈ 4.6 MB). That measured **≈ 40 GB/year** for 30 languages, 2.5× the
Phase 0 estimate. Small files compress poorly: the same article titles repeat in every hour of a day, and Parquet only
exploits that within one file.

## Decision

```
data/hourly/year=YYYY/month=MM/day=DD.parquet
```

- Each day file holds all ingested hours of that UTC day, with an unchanged schema (`ts_hour_start`, `lang`, `title`,
  `views_desktop`, `views_mobile`).
- Rows are sorted by `(lang, title, ts_hour_start)`, compressed with zstd level 9, in row groups of ≈ 1 M rows.
- Adding an hour means reading the day file, replacing that hour's rows and rewriting it (≤ ≈ 150 MB, a few
  seconds). Every writer (hourly job, backfill, `push`) uses `lookedup.store.write_hours`. It merges as of a Hub
  revision and commits with `parent_commit`. On a conflict it **redoes the merge** on the new revision, so a
  concurrent writer's hours are never lost. Hours already in the manifest are not overwritten.
- The manifest still tracks **hours** (`path` now points to the day file). A new `files` section records rows and
  bytes per day file (schema_version 2).
- `python -m lookedup.cli compact` migrates a Phase 1 local lake in place.

## Measurement

The local lake was migrated on 2026-10-08: 6 full days (1–6 Oct) plus 4 hours of 7 Oct.

| | Bytes per full day | GB/year |
|---|---|---|
| 24 hourly files (Phase 1) | 120.4 MB | ≈ 44 |
| 1 daily file | **44.4 MB** (0.37×) | **≈ 16.2** |

That is below the 25 GB/year budget, so retention **stays at ≥ 5 views/hour** (ADR 0007). The ≥ 10 fallback was not needed.

## Consequences

- Readers glob `data/hourly/*/*/*.parquet` and filter on `ts_hour_start`. One hour means reading one day file and
  filtering; row-group statistics on the sorted columns keep it cheap.
- The hourly job rewrites today's file every hour: about 24 uploads a day of a growing file (≤ 45 MB), which is fine for the Hub.
- Partial days (today, or gaps) are normal. The manifest, not the file, says which hours exist.
