# 0009 — Hourly job on GitHub Actions: idempotent and self-healing

- Status: accepted (project owner decision D6)
- Date: 2026-10-08

## Decision

`.github/workflows/hourly.yml` runs `python -m lookedup.cli hourly` at **:45 every hour**. Each run:

1. reads `data/manifest.json` from the Hub;
2. computes the expected hours of the last **72 h** (only hours that have ended);
3. diffs them against the manifest and the server listing;
4. processes **at most 6** published missing hours, newest first;
5. commits the files and the manifest in one commit;
6. logs one line per hour (rows, bytes, publication lag, download and processing time).

Hours already present are skipped. Hours not yet published are logged, with a warning after 6 h.
Downloads resume across the 256 MiB server cut. A failed upload fails the job.

## Consequences

- Late, dropped or duplicated cron runs cost nothing: the next run catches up (up to 6 hours per run, so a
  72-hour outage heals in about 14 runs).
- A gap older than 72 h is not healed by the hourly job. Use the backfill (ADR 0010).
- Concurrent writers (hourly, backfill, wikidata) are serialised by Hub optimistic concurrency, not by locks.

## Amendments (2026-10-08)

- **Missing configuration is not a failure.** If the `HF_TOKEN` secret is absent, the scheduled job emits a GitHub
  Actions warning annotation and exits 0. A real upload error still fails the job. The manual backfill still fails
  loudly without a token, because someone started it on purpose.
- **Pipelines write to the lake only.** Workflows run with `permissions: contents: read`, and no package code may run
  `git commit`/`git push` (guarded by `tests/test_no_git_in_pipeline.py`).
- Since ADR 0012, each run merges its hours into the day files through `lookedup.store.write_hours`.
