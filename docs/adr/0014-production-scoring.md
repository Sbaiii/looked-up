# 0014 — Production scoring: daily baselines, hourly spikes, events and latest.json

- Status: accepted
- Date: 2026-10-09

## Decision

- **Daily, 03:30 UTC** (`.github/workflows/daily.yml`, `python -m lookedup.cli baselines`):
  - build `data/baselines/day=D.parquet` from the 28 day files before D;
  - one row per `(lang, title, hour_of_day)` slot with a non-zero median for D's day type, plus one prior row per language;
  - keep the last 3 baseline files.
- **Hourly, after ingestion** (`hourly.yml`, `python -m lookedup.cli score`):
  - score every ingested hour of the last 48 h that is not yet scored and whose day has baselines, at most 6 per run;
  - append the candidates passing R1 or R2 with R3 ≥ 6 to `data/spikes/…/day=DD.parquet`;
  - rebuild events over the last two days into `data/events/…` and `data/events/languages/…`;
  - write `data/latest.json`: events of the last 24 h, top 50 by breadth then intensity, with labels in the 30
    languages and a category;
  - track progress in `data/scoring_state.json`.
- `--hour <ts>` scores exactly one hour.
- Rules and the event builder are the same code as the warehouse (`lookedup.analytics.scoring`, `.events`).

## Production-only approximations (batch evaluation is exact)

1. **Stored slots.** Only slots with a non-zero median are stored. A slot present on fewer than half of its
   observation days has median = MAD = 0 exactly (ADR 0013, I1), so dropping it loses nothing.
   - A title with **no** stored slot is treated as *unseen*: language prior, no R1.
   - Batch would give such a rarely-present title a zero baseline with R1 allowed, so production is slightly more
     conservative for those titles.
2. **Partial-day automation flags.** Production can't wait for the end of the UTC day, so it uses the hours so far.
   The flat rule needs ≥ 6 hours of data.
3. **Excess views** are summed over spike rows only. Production does not store non-spiking scored hours.
4. **QIDs, labels and classes** come from the Wikidata API at scoring time, only for spiking titles and event QIDs.
   The 600 MB sitelinks file is never downloaded hourly.
5. **Scoring waits for baselines.** Hours ingested before 03:30 UTC are scored by a later run once that day's baselines exist.

## Consequences

- A typical run downloads two day files, a baseline file and two spike files (≈ 150 MB), and adds a few seconds of DuckDB.
- Agreement between production and batch is to be measured on a held-out day and reported in the Phase 2 results.
- Baseline files are rewritten daily. To bound Hub storage history, old baselines are deleted, and periodic history
  squashing stays an option (ADR 0008).
