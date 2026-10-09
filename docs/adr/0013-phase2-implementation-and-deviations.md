# 0013 — Phase 2: implementation choices, interpretations and deviations

- Status: accepted
- Date: 2026-10-09, **written before any evaluation result was computed** (git timestamp)
- Relates to: [docs/prereg_phase2.md](../prereg_phase2.md), config/analytics.yml

The pre-registration is unchanged. This ADR records:

- **D:** deviations from the Phase 2 *instructions*;
- **I:** how ambiguous pre-registered wording was turned into code;
- **S:** one sensitivity analysis added after a data observation, before results.

## Deviations from the Phase 2 instructions

**D1. `stg_hourly` has no per-row QID join.**

- The instructions asked for "stg_hourly (typed, with qid join and mobile share)".
- Measured on 10 days (129 M rows), the view with a LEFT JOIN to the 57 M sitelinks took **1,051 s, against 0.87 s
  without it**. DuckDB does not eliminate an unused join.
- Within a language, a title maps to exactly one QID (the unique key of `wb_items_per_site`). So everything is computed
  per `(lang, title)`, and the QID is attached where it's needed: `int_spikes`, `dim_entities` and the event marts.
- Results are identical. Only the cost changes.

**D2. The manifest reconciliation test compares row counts, not view totals.**

The manifest stores rows per hour, not view sums. The singular test `assert_stg_rows_match_manifest` checks, for 3
hash-chosen days, that `count(*)` per hour in `stg_hourly` equals the manifest's `rows`.

## Interpretations of the pre-registration

**I1. Observations include zero-imputed days.** Prereg §1 imputes absent rows as 0 "in every computation". The
`>= 7 observations` requirement therefore counts **calendar days** of the right type in the lookback (clipped at
2026-07-09), not present rows. Medians and MADs are taken over the present values padded with zeros up to that count.

**I2. "Unseen"** means the `(lang, title)` has no retained row at all in the 28-day lookback. A title present on a few
days has median 0 and MAD 0 under I1. It is not unseen, and R1 stays allowed.

**I3. Language prior.**

- Median and MAD of hourly views over retained rows, with no zero padding, for titles seen on ≥ 7 distinct days in
  the lookback.
- It is computed on a deterministic **1/50 sample of titles** (`hash(lang || title) % 50 = 0`). An exact median over
  ≈ 350 M rows per scored day was not tractable on the analysis machine.
- If a language had no prior (an empty sample, which never happened on real data), the baseline falls back to 0.

**I4. Events and windows.**

- The spikes of a QID form episodes separated by ≥ 24 h without spikes.
- An episode is an event if a window `[t, t + 6 h)` starting at one of its spikes contains spikes in ≥ 3 languages.
- `start_hour` is the earliest such window start.
- `breadth`, `peak_intensity`, spread lags and excess views are measured over `[start_hour, start_hour + 24 h)`.

**I5. Excess views** are summed over the article-hours that were scored, those with ≥ 100 views. Hours below the R1/R2
floor are not scored, so their small excess is not counted.

**I6. Automation flags use the UTC day.** A `(lang, title, day)` is evaluated on that UTC day's 24 hours, with absent
hours = 0 in the coefficient of variation.

## Sensitivity analysis declared before results (S1)

While testing the pipeline on 2026-07-20, before any evaluation, the pre-registered **flat-series rule** (CV < 0.15 with
≥ 200 views/hour) was seen to flag clearly human traffic:

- `en:The_Odyssey_(2026_film)`: 864 k views, 76 % mobile, CV 0.12;
- `en:Gerard_Piqué`, `en:Marc_Cucurella`, `en:Jude_Bellingham`: 79–91 % mobile.

Very popular English articles are read around the clock, so their daily curve is flat. The low-mobile rule, in
contrast, caught `fr:Cookie_(informatique)` (0.6 % mobile) and `en:.xyz` (3.9 %).

The **primary analysis keeps the registered filter.** In addition, results are reported for one variant, fixed now:

- **S1 = automation filter with the flat rule switched off** (low-mobile rule only), for H1, the precision proxy, H3
  (share of non-events flagged, and events wrongly flagged) and the event count.

S1 is reported next to the primary configuration, never instead of it.
