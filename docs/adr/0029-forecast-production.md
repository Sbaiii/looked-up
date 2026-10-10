# 0029 — Forecasts in production: training data, calibration and what is shown

- Status: accepted
- Date: 2026-10-10
- Relates to: [docs/prereg_phase4.md](../prereg_phase4.md), ADR 0028, [phase 4 results](../analysis/phase4_results.md)

## Decisions

### Training data for the weekly retrain

- The runners have no warehouse, so the retrain reads its training data from the lake.
  - `data/models/training/batch.parquet` is the warehouse feature table (16 Jul – 6 Oct), uploaded once.
  - One `live-<monday>.parquet` per week is rebuilt from the production spike files and hourly day files.
- **Live M1 targets are exact**, because breadth comes from the same events.
- **Live M2 targets are an approximation.** Production has baselines only for candidate rows (ADR 0014), so a live
  week's `excess_next24` counts excess on candidate rows only. Non-candidate article-hours count as 0.
  - This under-counts slightly against the warehouse definition.
  - The pre-registered backtest is unaffected, since it used the warehouse table only.

### Calibration window

- The pre-registration says Platt scaling on the most recent 10 days. That is kept for the international models
  (95–262 positives).
- Planetary events are too rare: the last 10 days of training data held **none**, so the calibration fit was
  impossible.
  - The window now widens in 10-day steps, up to 40, until it holds ≥ 5 positives. Planetary ended at 30–40 days
    with 5–6 positives.
  - Those days are kept out of the model fit.

### What the app shows

- **Probabilities only for open events** (started < 24 h before the latest export), and never for a tier already
  reached.
- **Older day files freeze** with the forecasts of their last export. The app hides any forecast for an event more
  than 24 h old at the time of the latest `today.json`.
- **Thresholds** (from the brief):
  - "Spreading" when `p_international` ≥ 0.5;
  - the planetary chance only when ≥ 0.3;
  - the fade ETA only while it is still in the future.
- **The planetary models are shown with a warning.** The test window held only **3** planetary events, so their
  test AUC (0.79–0.98) and calibration (slope 0.39–0.98) are not reliable. The app says so in FIG. 05.
- **The fade ETA is shown, and the app says it is no better than a rule.** The pre-registered H8 concerns attention
  left (`excess_next24`), where the model wins by 26 %. For `fade_hours`:
  - the model does **not** beat the category median: MAE (log1p) 0.638 vs 0.619;
  - most events have already fallen below half their peak by t0 + 3 h.

## Consequences

- Live training data grows by one file a week. The retrain uses every file, so later models learn from production
  features directly.
- If a later backtest shows the fade model still doesn't beat the rule, the ETA should be replaced by the rule's
  answer ("probably fading already").
