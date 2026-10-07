# 0001 — Pageview sources: hourly dumps live, pageview_complete for history

- Status: accepted
- Date: 2026-10-07
- Evidence: [feasibility §1, §2, §5](../feasibility.md)

## Context

"What is the world paying attention to right now" needs per-article counts at hourly resolution in many
languages. Candidates: hourly `pageviews` dumps, daily `pageview_complete` files (hourly counts inside),
the pageviews REST API.

## Decision

- **Live ingestion:** hourly `pageviews` dumps (`pageviews-YYYYMMDD-HH0000.gz`, filename = *end* of the hour).
  Wikipedia rows only (`xx`, `xx.m`), desktop and mobile **summed**, `bytes` column dropped.
- **Backfill and baselines:** `pageview_complete` user files (one bz2 per day, includes `page_id`).
- **REST API:** spot checks and the daily per-country overlay only, never bulk.

## Consequences

- Data is ≈ 2.2 h (median) behind the hour it describes. The product speaks of the last few hours, not seconds.
- The two dump sources were identical on 179/179 overlapping (hour, title) pairs, so mixing them is safe.
- Dumps contain `user` traffic only, which still includes bot-like traffic. Noise filters are mandatory.
