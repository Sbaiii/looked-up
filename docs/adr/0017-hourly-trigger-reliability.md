# 0017 — Hourly trigger reliability: uncommon cron minute, external trigger, wider catch-up

- Status: accepted; amends ADR 0009
- Date: 2026-10-09

## Context

- With `cron: "45 * * * *"`, GitHub ran the scheduled hourly workflow only **twice** (2026-10-08 19:25 and 23:57 UTC)
  in the first ~10 hours, and not at all in the following 6 hours.
- The workflow is `active` and the repo has recent commits, so the 60-day inactivity rule is not the cause.
- GitHub documents that scheduled runs can be delayed or dropped under load, especially at the top of the hour.

## Decision

1. Move the schedule to **minute 17** (`"17 * * * *"`), away from the busiest minutes.
2. Add `.github/workflows/trigger.yml`, a second path. A `repository_dispatch` event of type `hourly-tick`, sent by
   an external free pinger (cron-job.org), dispatches `hourly.yml`. Setup and token scopes are in
   [docs/ops.md](../ops.md).
3. Widen self-healing: each run looks back **7 days** (was 72 h) and processes up to **12 hours** (was 6). Scoring
   uses the same window and cap.

## Consequences

- At 2 runs per 8 hours, 12 hours per run still keeps up (24 hours of capacity per 8 hours). A full day of outage
  heals within 2 runs.
- Duplicate ticks (cron plus pinger) are harmless: runs are idempotent, and the concurrency group queues them.
- A fine-grained PAT used by the pinger must be stored outside GitHub. Its scope is in docs/ops.md.
