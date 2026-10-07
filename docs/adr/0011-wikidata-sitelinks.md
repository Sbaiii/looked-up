# 0011 — Wikidata sitelinks for the active languages, refreshed monthly

- Status: accepted (project owner decision D8). Refines ADR 0003.
- Date: 2026-10-08

## Decision

Build `data/wikidata/sitelinks.parquet` with columns `lang VARCHAR`, `title VARCHAR` (underscores) and
`qid INTEGER` (numeric part, Q597 → 597). It covers the active languages only and is sorted by (lang, title).
The source is `wikidatawiki-latest-wb_items_per_site.sql.gz` (1.9 GB), streamed line by line and written in batches.
It is never fully held in RAM. `.github/workflows/wikidata-monthly.yml` rebuilds it on the 8th of each month,
after the monthly dump run.

## Consequences

- The join is `hourly.lang = sitelinks.lang AND hourly.title = sitelinks.title`. Coverage per language is in
  [wikidata_coverage.md](../wikidata_coverage.md).
- Redirects and articles newer than the dump do not match. Redirect resolution is future work.
