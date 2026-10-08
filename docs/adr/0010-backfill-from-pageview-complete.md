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

`python -m lookedup.cli validate -n 3` rebuilds random backfilled hours from the hourly dumps and compares them row by row.
The test suite checks the transformation offline on real excerpts of 2026-09-13 14:00, where the two paths are identical.

On real full hours the sources are **not quite identical**. 2026-10-08, six random hours from 4–6 Oct:

| Hour (UTC) | Rows matching exactly | Views, backfill vs hourly dump |
|---|---|---|
| 2026-10-06 10:00 | 481,042 of 481,046 | 1 row only in backfill, 4 only in the dump |
| 2026-10-05 17:00 | 99.9988 % | 10,804,224 vs 10,804,265 |
| 2026-10-04 19:00 | 99.9991 % | 14,105,806 vs 14,105,852 |
| 2026-10-06 02:00 | 99.9993 % | 8,166,058 vs 8,166,084 |

The differing rows are low-volume and mostly mobile: pages that do not exist (`no:Statistikkbank`,
`ru:Конкурсы/Дорога_в_космос`), a redirect (`pl:Strona_główna`), and a small article (`ru:Форум`). The hourly dump
always has the higher mobile count. Our two code paths are identical on the same input, so this is an
**upstream difference**: `pageview_complete` appears to under-count a few mobile views, mostly on pages without a
page id. That is our interpretation; it is not documented by Wikimedia. The effect is about 0.001 % of rows and
0.0003 % of views. `validate` fails only when fewer than 99.99 % of rows match.

## Consequences

- Both paths share one transformation (`lookedup.transform`), so the sources are interchangeable per hour.
- `pageview_complete` appears ≈ 2.4 h after the UTC day ends. It cannot serve the live path.
