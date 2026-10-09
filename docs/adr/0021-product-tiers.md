# 0021 — Product tiers by breadth (min two languages)

- Status: accepted
- Date: 2026-10-09
- Relates to: ADR 0015 (event definitions), ADR 0019 (single-language events), Phase 2/2b results

## Context

Phases 2 and 2b evaluated one threshold: an event needs spikes in ≥ 3 languages within 6 h. The Phase 2b ablation
showed this threshold is the main lever on recall. At ≥ 2 languages, 56 % of notable deaths are detected; at ≥ 3,
32.5 %; at ≥ 5, 9 %. A product doesn't need one cut-off. It can show everything and say how wide it spread.

## Decision

- The product uses **min_languages = 2** (`config/product.yml`). Window, R3, gap and breadth window are unchanged.
- Every event gets a **tier** from its breadth (languages spiking within 24 h of the start):

  | Tier | Breadth |
  |---|---|
  | `noticed` | ≥ 2 |
  | `international` | ≥ 5 |
  | `planetary` | ≥ 20 |

- The tier is computed in the shared event SQL (`events_sql`), so the warehouse and the hourly scorer can't drift.
- Single-language events (ADR 0019, lead share ≥ 95 %) keep their own list whatever their tier.
- **Where it applies:**
  - The hourly scorer (`data/events/`, `latest.json`) now writes product events.
  - The warehouse gets new marts `fct_app_events` and `fct_app_event_languages`.
  - The pre-registered `fct_attention_events` (min 3) is **kept unchanged**, so the Phase 2 and 2b evaluations stay
    reproducible. `config/analytics.yml` is untouched.

## Effect on the batch (16 Jul – 7 Oct 2026, 84 days)

- Events rise from 11,127 (min 3) to **37,386** (min 2).
- Every primary event has a product counterpart for the same spike episode. 9,596 have the same start hour (same
  `event_id`). The other 1,531 start earlier, because two languages cross before the third does.

| Tier | Multi-language | Single-language | Total |
|---|---:|---:|---:|
| planetary | 124 | 0 | 124 |
| international | 3,803 | 53 | 3,856 |
| noticed | 29,457 | 3,949 | 33,406 |
| **Total** | **33,384** | **4,002** | **37,386** |

## Consequences

- "Noticed" events are noisier: a two-language co-spike is weaker evidence. The tier tells readers how much to trust
  an event, and the app defaults to sorting by breadth.
- Lake `data/events/` files written before this change (from 8 Oct) used min 3. The app's day files are rebuilt from
  spikes with the product settings, so they are consistent.
