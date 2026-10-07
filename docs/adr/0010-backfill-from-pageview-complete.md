# 0010 — Backfill 90 days from pageview_complete

- Status: accepted (project owner decision D7)
- Date: 2026-10-08

## Decision

`python -m lookedup.backfill --from 2026-07-09 --to 2026-10-06` fills the lake from `pageview_complete` (one bz2 per
day with hourly counts), using the same schema and layout and `source = pageview_complete` in the manifest.

It is resumable. A day whose 24 hours are all present is skipped. Downloads resume. Each day is its own commit.
Hours already ingested from hourly dumps are never overwritten. The same job can run on Actions
(`.github/workflows/backfill.yml`, manual).

## Validation

`python -m lookedup.cli validate -n 3` rebuilds random backfilled hours from the hourly dumps and requires
exact equality. The test suite checks the same property offline on real excerpts of 2026-09-13 14:00.

## Consequences

- Both paths share one transformation (`lookedup.transform`), so the sources are interchangeable per hour.
- `pageview_complete` appears ≈ 2.4 h after the UTC day ends. It cannot serve the live path.
