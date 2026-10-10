# 0033 — Live-layer state in D1, five poll groups

- Status: accepted (builds on ADR 0032)
- Date: 2026-10-10

## Context

With KV as the only store, ADR 0032 could afford 3 poll groups: KV allows 1,000 writes a day. That left runs at
8–13 ms of CPU, against the free plan's 10 ms. The fixed cost of each run's API calls dominates, so smaller groups
are the lever, and that needs a store with more write headroom. The token now has **Account › D1 › Edit**.

## Decision

- **D1 database `looked-up-live`** (binding `DB`, schema in `worker/migrations/`, created and migrated by
  `worker.yml`):
  - `group_state`: **one row per poll group**. It holds that group's per-article windows, the 64-bit editor
    sketches, baselines, poll positions and coverage, as compact JSON.
  - `bursts`: one row per burst (no user data), kept 7 days.
  - `pings`: GETs to `/health` from cron-job.org per day, with the last user agent (the pinger check).
- **Five groups of 6 wikis**, dealt round-robin by rank. One group runs per minute (`* * * * *`, minute m → group
  m mod 5), so each wiki is still polled every 5 minutes. The per-poll logic is unchanged.
- **KV keeps only:**
  - the QID cache (`q:<lang>|<title>`, `i:<QID>`, 30-day TTL), written only for new burst titles;
  - cached responses (`resp:/live.json` for 5 min, `resp:/stats.json` for 30 min).
- **Reads** go edge cache (15 s) → KV response cache → a render from D1 (5 group rows + bursts).
- **Why not one D1 row per article?** About 2.8 kept edits a second touch about 240,000 article-slots a day. That
  would be 240k row writes, over D1's free 100k. A row per group writes 1,440 a day.

## Expected daily use vs the free limits

| Resource | Expected per day | Free limit | Share |
|---|---:|---:|---:|
| D1 rows written | 1,440 group rows + ≈ 100–300 bursts + the same in prunes + 24 pings ≈ **2,000** | 100,000 | 2 % |
| D1 rows read | polls 1,440 + `/live.json` renders ≤ 288 × (5 + ≈ 20 bursts in the hour's range) + `/stats.json` renders ≤ 48 × (5 + ≈ 1,500 bursts of 7 days) + `/health` ≈ 24 × 5 ≈ **90,000** | 5,000,000 | 2 % |
| D1 storage | ≈ 5 rows × ≤ 100 KB + ≈ 2,000 bursts × 100 B ≈ **1 MB** | 5 GB | ≈ 0 % |
| KV writes | QIDs and items ≈ 200–400 + responses ≤ 288 + 48 ≈ **≤ 750** | 1,000 | ≤ 75 % |
| KV reads | QID lookups ≈ 300 + response cache misses after the edge cache ≈ a few thousand | 100,000 | < 5 % |
| Worker invocations | 1,440 cron + HTTP requests (edge-cached) | 100,000 | ≈ 2 % + traffic |

`stats.json` reads count every burst of the week. They are rendered at most every 30 minutes thanks to the KV
cache.

## Consequences

- Every minute runs a poll of 6 wikis, so every run does work.
- The CPU target is p95 < 8 ms per poll, measured with `worker-observe.yml`. The results are below.
- The unchanged burst logic is guarded by the 12 core tests. The repository layer and a full persisted poll are
  tested against a local D1 in miniflare (`worker/test/repo.test.ts`).
