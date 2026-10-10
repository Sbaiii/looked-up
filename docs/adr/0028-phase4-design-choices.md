# 0028 — Phase 4 design choices that differ from the brief

- Status: accepted, recorded with the pre-registration (before any model was trained)
- Date: 2026-10-10
- Relates to: [docs/prereg_phase4.md](../prereg_phase4.md)

| Brief | Pre-registered | Why |
|---|---|---|
| Events from 16 Jul "to yesterday" (9 Oct) | to **6 Oct 23:00** | The warehouse period ends 7 Oct (pre-registered Phase 2 config), and targets need 24 h after the start. Later events exist only as production approximations. |
| t0 = "first scored hour" | t0 = **detection hour**: the hour the second language spikes | `start_hour` is often hours before the event is knowable (the second language can follow up to 5 h later). Features at `start_hour` would condition on knowing the future. |
| Class weights | class weights **plus Platt scaling on validation** | Weighting inflates probabilities. Without recalibration, H6's calibration slope would fail by construction. |
| Evaluate on all snapshots | primary metrics on snapshots that have **not yet reached** the tier; all-row metrics descriptive | A forecast is only useful, and only shown (Step 3), for tiers not yet reached. Already-reached rows would inflate AUC trivially. |
| Days since article creation | **not used** | Not cheap: one revision query per article and language. |
| — | sensitivity model without `n_sitelinks` and `is_death` | Both may leak: sitelinks are from 7 Oct, death claims fetched afterwards. |
| Rolling origin, retrain weekly | 4 weekly folds, each trained up to 7 days before the week and calibrated on those 7 days | Same calibration scheme as the main split. Weekly fold boundaries are fixed in advance. |
