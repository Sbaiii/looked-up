# Phase 4 pre-registration: forecasting event spread and duration

- Registered: 2026-10-10, **before any forecasting code, feature table or model existed** (git timestamp).
  `docs/prereg_phase2.md`, `docs/prereg_phase2b.md` and `config/analytics.yml` are unchanged.
- **Population.** Product events (ADR 0021: ≥ 2 languages within 6 h) that are `multi_language` (ADR 0019).
  Source: the warehouse marts `fct_app_events` and `fct_app_event_languages`.
- **Period.** Events with `start_hour` from 2026-07-16 00:00 to **2026-10-06 23:00** UTC.
  - The warehouse period ends on 7 Oct 23:00 (`config/analytics.yml`). Events must have their full 24 h target
    window inside it, so "16 Jul to yesterday" becomes 16 Jul to 6 Oct.
  - Live events after 7 Oct exist only as production approximations (ADR 0014) and are not used for evaluation.
- Any change to the definitions below after data is seen is a deviation and goes in an ADR.

## Decision time (no leakage)

- **t0 is the detection hour:** the hour in which the event's **second** language first spikes (R3 ≥ 8). It is the
  first hour at which the hourly job can know the event exists.
  - The event's `start_hour` is often earlier, because it is the first spike of the window. Using it as t0 would
    condition on knowing the future.
- **Snapshots at T = t0, t0 + 1 h and t0 + 3 h.** A snapshot is kept only if T < `start_hour` + 24 h.
- **Features use only data with `ts_hour_start ≤ T`:**
  - rows from the event's episode (`ts_hour_start ≥ start_hour`);
  - **candidate rows only**, i.e. R1 or R2, surprise ≥ 6, not automated, with a QID. These are exactly what
    production stores, so batch and live features are identical.
  - Views shape features use article-hours with ≥ 100 views (`int_baselines`). Production rebuilds them from the hourly
    day files with the same floor.
- **A dbt test recomputes two features** (`breadth_t`, `max_surprise_t`) from `int_spikes` for 50 random rows.
  It fails on any mismatch.

## Features (all at snapshot time T)

| Feature | Definition |
|---|---|
| `lead_lang` | the event's lead language (fixed at `start_hour`, so known at T) — categorical |
| `breadth_t` | distinct languages with a spike (R3 ≥ 8) in [`start_hour`, T] |
| `max_surprise_t`, `sum_surprise_t` | max and sum of surprise over those spikes |
| `excess_t` | Σ max(views − baseline median, 0) over the candidate rows in [`start_hour`, T] |
| `lead_share_t` | the lead language's share of `excess_t` |
| `new_langs_last_hour` | languages whose first spike is in hour T |
| `hours_since_start` | T − `start_hour` |
| `entity_class` | coarse P31 class from `dim_entities` — categorical |
| `is_death` | `category = 'death'` |
| `hour_utc`, `weekday` | of T |
| `n_sitelinks` | articles among our 30 languages (`dim_entities.n_languages`), i.e. fame |
| `views_t`, `views_slope`, `peak_views_so_far`, `lead_views_share` | total views of the event's known articles at T; log1p(views at T) − log1p(views at T − 2); max hourly total in [`start_hour`, T]; lead language's share of views in [`start_hour`, T] |

- `days since article creation` is **not used**: it isn't cheap (one revision query per article and language).
- **Known leakage risks, declared now.**
  - `n_sitelinks` comes from the 7 Oct sitelinks dump. Articles created *because* of an event (e.g. new translations
    after a death) can inflate it.
  - `is_death` relies on P570 claims fetched after the event.
  - A **sensitivity model without `n_sitelinks` and `is_death`** is reported. It does not decide any verdict.

## M1: "Will it go global?"

- **Targets** (from the event table, unchanged):
  - `reach_international`: breadth ≥ 5 within 24 h of `start_hour`;
  - `reach_planetary`: breadth ≥ 20.
- **Evaluation rows** for a target: snapshots whose `breadth_t` is still **below** the target's threshold. That is
  the only case where a forecast is useful, and the app never shows a probability for a reached tier. All-row metrics
  are reported too, descriptively.
- **Model.** LightGBM binary classifier, one per target and offset (6 models).
  - Monotone increasing constraints on `breadth_t`, `max_surprise_t`, `sum_surprise_t`, `excess_t` and `n_sitelinks`.
  - Class weights: `scale_pos_weight` = negatives / positives on train.
  - **Calibration:** Platt scaling (a logistic regression on the model's logit), fitted on validation, because class
    weights distort probabilities.
- **Baselines:**
  - (a) base rate on train;
  - (b) the rule "`breadth_t ≥ 3`" (as a score: `breadth_t`);
  - (c) logistic regression on log1p(`n_sitelinks`) alone.
- **Metrics:**
  - ROC AUC and PR AUC (average precision);
  - Brier score;
  - calibration curve in 10 equal-width bins, and calibration slope (logistic regression of y on logit(p));
  - lift in the top 10 % of scores.

## M2: "How long will it last?"

Rows: snapshots at **T = t0 + 3 h**.

- **Targets:**
  - `excess_next24`: Σ max(views − baseline median, 0) over hours (T, T + 24]. It covers the articles of **every**
    language that spikes in the event, using article-hours with ≥ 100 views; missing hours count as 0.
  - `fade_hours`: hours from T until the first hour, at or after both T and the event's peak hour, in which the event's
    total hourly views fall below half of the peak.
    - The peak is the max hourly total in [`start_hour`, `start_hour` + 72 h].
    - Capped at 48 h. Events whose T + 48 h passes the data end (7 Oct 23:00) are excluded from fade metrics only.
- **Model.** LightGBM regression on log1p(target), using the M1 features plus the shape features.
- **Baselines:**
  - **persistence**: excess in hour T × 24 (for fade: the hours since the peak so far, mirrored);
  - **category-median decay**: the training median of `excess_next24 / excess in hour T` per `category`, times the
    current hour's excess (for fade: the category's median `fade_hours`).
- **Metrics:**
  - MAE on log1p;
  - MAPE on log1p, i.e. mean |ŷ − y| / y over rows with y > 0;
  - for fade, the median absolute error in hours.

## Splits, tuning and folds

- **Train:** events starting before 2026-09-10.
- **Validation:** 2026-09-10 to 2026-09-19.
- **Test:** 2026-09-20 to 2026-10-06, scored **once**, in the final run.
- **Hyperparameter search:** on validation only, **50 random trials** per model, with a fixed seed (20261010).
  - Space: `num_leaves` 7–63; `learning_rate` 0.02–0.2 (log); `n_estimators` 100–800; `min_child_samples` 20–200;
    `feature_fraction` 0.6–1.0; `lambda_l2` 0–10.
  - Objective: validation PR AUC for M1, validation MAE (log1p) for M2.
- **Test models** are trained on train only with the chosen parameters. M1 is then Platt-calibrated on validation.
- **Rolling origin (4 folds),** test weeks [10 Sep, 17 Sep), [17, 24), [24 Sep, 1 Oct), [1 Oct, 7 Oct).
  - Each fold trains on events before the week minus 7 days, calibrates on those 7 days, and scores the week.
  - Folds use the chosen parameters. They are reported for M1 (international, t0 + 1 h) and M2 (`excess_next24`).
- **Permutation importance** on validation: 5 repeats, metric PR AUC (M1) or MAE (M2).

## Hypotheses

| ID | Claim | Rejected if |
|---|---|---|
| **H6** | `reach_international` at t0 + 1 h, test: ROC AUC ≥ 0.80 **and** calibration slope in [0.8, 1.2] | either fails |
| **H7** | Fame dominates: baseline (c), sitelinks alone, reaches ≥ 70 % of the model's PR AUC (`reach_international`, t0 + 1 h, test) | ratio < 0.70 |
| **H8** | M2 beats category-median decay by ≥ 20 % MAE (log1p `excess_next24`, test) | model MAE > 0.8 × baseline MAE |

**Expectation, stated before running.** We expect **fame to dominate**, i.e. H7 to hold. The number of language
editions with an article predicts how far attention can spread. The model's extra value should come from the early
spread itself (`breadth_t`, `new_langs_last_hour`, `excess_t`).

## Production (not evaluated here)

- Weekly retrain (Mondays) on all events up to 10 days ago, Platt-calibrated on the most recent 10 days, with the
  chosen parameters.
- Every open event (started < 24 h ago) is scored hourly with the model for the largest offset ≤ its age since t0.
- Probabilities are exported only for tiers not yet reached.
