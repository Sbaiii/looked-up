# 0033 — Live-layer state in D1, five poll groups

- Status: accepted, **frozen** on 2026-10-10 (builds on ADR 0032). No further CPU work unless Cloudflare starts rejecting runs.
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
- The CPU target was p95 < 8 ms per poll, measured with `worker-observe.yml`. **It was not met.** See below.
- The unchanged burst logic is guarded by the 12 core tests. The repository layer and a full persisted poll are
  tested against a local D1 in miniflare (`worker/test/repo.test.ts`).

## Measured (30-minute tail, 2026-10-10 13:52–14:22 UTC, 30 polls, all `ok`)

| Group | Wikis | CPU per run, steady (ms) | p95 | Rows fetched per poll | State row |
|---|---|---|---:|---|---:|
| 0 | en es fa sv he ro | 11, 14, 16, 16, 16 | 16 | 311–412 (median 366) | 111 KB |
| 1 | ja it nl ko vi no | 9, 11, 11, 12, 13 | 13 | 142–191 | 50 KB |
| 2 | de zh ar cs hu sr | 8, 9, 9, 9, 10 | 10 | 117–154 | 42 KB |
| 3 | ru pt tr fi el bg | 6, 7, 7, 7, 7 | 7 | 43–85 | 19 KB |
| 4 | fr pl id uk th hi | 8, 9, 9, 11, 11 | 11 | 146–172 | 55 KB |

- **All runs:** median 9 ms, p95 16 ms. The cold first runs: median 10 ms, max 15 ms. **Not under 10 ms.**
- **D1 rows written:** about 66 an hour (one row per poll, plus new bursts), so about 1,600 a day against the free
  100,000.
- **`/health` used 7–12 ms CPU per request,** because it parses all five group rows.

### Why D1 did not close the gap

- **Group 0 holds English,** about 360 rows per poll over up to 3 pages. Its state row is 111 KB, and every run
  parses and re-serialises it. The fixed per-call cost of D1 and KV, and the JSON work on that row, kept it at
  11–16 ms. Groups with smaller wikis run at 7–10 ms.
- So the cost is now per-row JSON and per-wiki volume, not the number of groups.
- **Next options**, not taken here, pending the owner's decision:
  1. Give English its own group, and split its state by 5-minute slot so a run only parses the current window.
  2. Store articles in a binary layout instead of JSON.
  3. Make `/health` read a tiny summary row instead of all five states.
- **No switch to the paid plan.** Cloudflare has not throttled any run. Every one of 70+ tailed runs, up to 76 ms
  earlier today, ended `ok`.

### Pinger check

- `wrangler tail` showed `GET /health` from `Mozilla/4.0 (compatible; cron-job.org; http://cron-job.org/abuse/)` at
  14:00, 14:10 and 14:20 UTC.
- D1 counts these GETs in `pings`, and `/health` reports them as `pinger_today`.

## Final round (the last three changes) and freeze

1. **English polls alone.** Six groups: en, plus five groups balanced by measured edits per 5 minutes (113–116 rows
   each, `worker/src/groups.json`).
   - One group runs per minute, so each wiki is polled every **6** minutes.
   - The window state is stored **per 5-minute slot** (`slots`, one row per slot, rolling 70 minutes, old rows
     deleted) for every group: it fits the write budget easily.
2. **Compact encoding.**
   - Each slot row stores its article keys once, then a flat `[edits, bitsHigh, bitsLow]` array.
   - A small meta row holds poll positions, baselines and the few per-article extras.
   - The per-title hourly counts are gone: the hourly baseline is rebuilt from the slots.
   - Measured on the same 30-minute English sample (1,572 articles, `worker/test/fixtures/`):

   | Layout | Size |
   |---|---|
   | v5 group blob, read and rewritten every run | 100.8 KB |
   | New slot rows read (whole window) | 68 KB |
   | New meta row | 2 KB |
   | New writes per steady run (latest slot + meta) | 13.7 KB |

3. **Summary row per group.** `/health`, `/stats.json` and `/live.json` read only these and the bursts table. `/health`
   now costs **3–6 ms** of CPU, down from 7–12 ms.

### Final measurements (30-minute tail, 15:27–15:57 UTC, 30 polls, all `ok`)

| Group | Wikis | Steady CPU per run (ms) | Median | p95 | Rows per poll |
|---|---|---|---:|---:|---|
| 0 | en | 11, 15, 16, 17 | 15.5 | 17 | 399–488 |
| 1 | fr uk hu sv sr | 9, 9, 10, 12 | 9.5 | 12 | 136–177 |
| 2 | de pt ar vi ro bg | 10, 10, 11, 14 | 10.5 | 14 | 137–148 |
| 3 | ja pl nl fa id no | 8, 9, 9, 10 | 9.0 | 10 | 94–120 |
| 4 | ru zh ko tr el hi | 9, 9, 10, 10 | 9.5 | 10 | 93–129 |
| 5 | it es he fi cs th | 9, 10, 10, 11 | 10.0 | 11 | 143–195 |

- **All steady runs:** median 10 ms, p95 16 ms. Cold first runs: median 11 ms, max 15 ms.
- **D1 rows written:** 4.4 per poll, about **6,400 a day**, against the free 100,000 (6 %).

### Where it stands against the 10 ms limit

**Not met. Tolerated in practice.**

- About half the runs are at or under 10 ms.
- The English group stays at 11–17 ms, because one poll fetches about 450 edits.
- Cloudflare has rejected **none** of the **85 polls tailed on 2026-10-10**, including runs up to 76 ms under the
  earlier layouts, and none of the HTTP requests.
- The Worker is frozen as it is. The daily job warns if `/health` reports a full-hour gap, `connected: false` or
  no answer. That is the signal that would reopen this.
