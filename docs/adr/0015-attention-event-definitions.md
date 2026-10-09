# 0015 — Attention event definitions (Phase 2)

- Status: accepted
- Date: 2026-10-09
- Source of truth: [docs/prereg_phase2.md](../prereg_phase2.md) (pre-registered 2026-10-08) and config/analytics.yml

## Decision

Looked Up defines an **attention event** exactly as pre-registered:

- **Unit:** `(lang, QID, hour)`. Titles without a QID keep the key `lang:title`.
- **Automation filter:** a `(lang, title, day)` is flagged if it has ≥ 500 views and < 5 % mobile, or a flat series
  (CV < 0.15 at ≥ 200 views/hour). Flagged rows are kept but excluded from spikes.
- **Baseline:** median and MAD over the previous 28 days, per hour of day and day type; ≥ 7 observations; absent = 0.
  Fallbacks: hour of day, then a language prior for unseen entities.
- **Spike:** R3 (surprise ≥ 8) and (R1 views ≥ 5 × yesterday's same hour, or R2 ≥ 3 × the median of the previous
  3 hours, with ≥ 100 views). Unseen entities need R3 and R2.
- **Event:** a QID spiking in ≥ 3 languages within a 6-hour window; episodes separated by ≥ 24 h.
- **Attributes:** start, lead language, breadth (24 h), peak, excess views, spread lags and category.

Implementation choices are in ADR 0013. Production scoring follows ADR 0014.

## What the evaluation showed (2026-10-09, docs/analysis/phase2_results.md)

- **H1 rejected:** 4.3 % recall of Current events entries within 6 h.
- **H2 rejected:** the lead language matches the country in 40.7 % of geolocatable events.
- **H3 inconclusive.**
- **H4 rejected, reversed:** scheduled sports and TV attention spreads faster than deaths and disasters.
- The ablation winner (R3 ≥ 12, 3 languages, 12 h) is within 0.002 of the primary configuration on the
  pre-registered criterion.

## Consequences

- The definitions stay as they are for the live product, because the alternatives tested are no better.
  Any change is a new, logged decision.
- **For Phase 3, without changing the registered numbers:**
  - Weight multi-language confirmation by each language's surprise. The 3-language rule passes events where two
    languages barely move.
  - Add subclass-aware categories.
  - Evaluate against a ground truth that includes deaths and non-English sources.
