# 0031 — Refreshing the warehouse past the registered period

- Status: accepted
- Date: 2026-10-10

## Context

The local warehouse stopped at 7 Oct, the pre-registered end in `config/analytics.yml`. Phase 5 needs events up to
9 Oct, and the file must not change.

## Decision

- **`LOOKEDUP_PERIOD_END` overrides `AnalyticsConfig.period_end`**, and with it the dbt `period_end` var.
  - Only `python -m lookedup.cli refresh-warehouse` sets it: it mirrors new day files from the lake, then runs
    `dbt build`. The `int_*` models are incremental by day; the marts are rebuilt.
  - Without the variable, everything reads the registered end. The Phase 2/2b evaluations filter on it, so they
    reproduce unchanged.
  - The Phase 4 backtest has fixed split dates and a frozen copy of its feature table
    (`data/models/training/batch.parquet`).
- **Measured on 2026-10-10** (extending 7 Oct → 9 Oct, two new days):
  - 4 min 6 s in total: 40 s to sync, 203 s for dbt; 64 dbt tests passed.
  - Peak resident memory 6.1 GB.
  - It needs the existing 3 GB warehouse file and the 4.3 GB lake mirror.
- **It is a weekly manual step, not part of the Monday job.** A GitHub runner has neither the warehouse nor the
  mirror. Rebuilding from scratch means mirroring ≈ 4.5 GB and recomputing 90 days of baselines, which took hours
  locally in Phase 2. That is past what a scheduled job should do every week. Documented in `docs/ops.md`.

## Consequences

- The warehouse is only as fresh as the last manual refresh. Production scoring, the app and the forecasts don't
  depend on it: they read the lake.
