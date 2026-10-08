# 0008 — Lake on Hugging Face: layout, schema, manifest, hour alignment

- Status: accepted (project owner decision D5); the one-file-per-hour layout is superseded by ADR 0012 (one file per day).
- Date: 2026-10-08
- Details: [data_model.md](../data_model.md)

## Decision

Public dataset repo **`Sbaiii/looked-up`**:

```
data/hourly/year=YYYY/month=MM/day=DD/hour=HH.parquet   # zstd, one file per hour
data/wikidata/sitelinks.parquet                          # (lang, title, qid)
data/manifest.json                                       # every hour present
```

Hourly schema: `ts_hour_start TIMESTAMP` (UTC, naive), `lang VARCHAR`, `title VARCHAR`, `views_desktop INTEGER`,
`views_mobile INTEGER`. The manifest records per hour: path, row count, bytes, `source`
(`hourly_dump` | `pageview_complete`) and ingestion time. Every write commits the data files and the updated
manifest **in one Hub commit** with `parent_commit` set (optimistic concurrency, retried on conflict).

## Hour alignment

Dump filenames carry the **end** of the hour: `pageviews-20261007-120000.gz` covers 11:00–12:00 UTC, so
`ts_hour_start = file timestamp − 1 h`. Verified twice against the REST API:

- Phase 0: the en total in `…-100000.gz` equals the REST hour `2026100709` exactly.
- 2026-10-08: the en total in `…-120000.gz` is 7,163,227, equal to the REST hour starting 11:00 (the hour starting
  12:00 has 8,007,451). Re-run with `python -m lookedup.cli verify-hour --hour 2026-10-07T11:00`.

## Consequences

- One file per hour means about 8,760 Hub commits a year from the hourly job. HF warns that UX degrades after
  "a few thousand commits", so squash history periodically (`super_squash_history`) and keep the manifest as the
  source of truth.
- Measured size: ≈ 4.6 MB and ≈ 460 k rows per hour for 30 languages, so ≈ 40 GB a year. That is about 2.5× the
  daily-compacted estimate from Phase 0, because hourly files lose cross-hour compression. Compacting closed months
  into daily files is the fallback if Hugging Face storage pushes back.
