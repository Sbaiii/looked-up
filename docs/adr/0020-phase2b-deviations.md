# 0020 — Phase 2b deviations and data issues

- Status: accepted
- Date: 2026-10-09
- Relates to: [docs/prereg_phase2b.md](../prereg_phase2b.md) (unchanged)

## Context

The Phase 2b metrics were computed exactly as pre-registered (`docs/analysis/phase2b_metrics.json`). Reading the
per-item outputs exposed parsing and data issues. They are logged here. **None of them changes a verdict, and the
verdicts are based on the pre-registered computation only.**

## GT1: first-wikilink parse (post-hoc sensitivity, not a correction)

- The rule "the target is the first wikilink of the bullet" sometimes picks a non-person: a bullet that links a
  publication, place or organisation before the name (`IMDb` ×3, `Berlin`, `Aragon`, `Ivano-Frankivsk`,
  `Islamic Revolutionary Guard Corps`, `Russian Orthodox Church`, `2026 Broad Peak avalanche`, …).
  - 19 of 489 in-window items are affected.
  - These items are almost all broadly linked (20–30 languages), so they depress recall in the ≥ 20 languages bucket.
- **Post-hoc variant `person_link`:** these 19 items are dropped (items whose target is not a human are
  excluded). Recall becomes 158 / 470 = **33.6 %** (vs 32.5 %).
- **Post-hoc variant `early_24h`:** the window opens 24 h before the listed day instead of 12 h. Some attention
  starts before the listed (local) date, e.g. Harald V and Franco Baresi. Recall becomes 161 / 489 = 32.9 %.
- Both variants together: 160 / 470 = 34.0 %.
- All variants stay far below the 60 % threshold, so H1b-1 is rejected either way. Output:
  `docs/analysis/phase2b_gt1_variants.json`.

## GT2: Wikidata quake matching noise

- **Mexico, M7.3, 2026-07-17.** The pre-registered "closest coordinates" rule matched the item
  `Q140616464` ("2026 Huancayo earthquake", Peru), whose Wikidata coordinates are wrong. The true Mexican quake had
  no qualifying item. Neither target was detected, so the outcome is a miss under any matching. The Mexico M6.4
  aftershock inherits the same item.
- **Kumamoto, M6.8, 2026-07-28.** USGS gave the place as "The 2026 Kumamoto Region, Japan Earthquake". That string
  isn't in the "…of LOCALITY, REGION" form, so no place target was resolved. The earthquake article (a) was found and
  detected, so no change.
- **Targets (b) can be coincidental.** Flores M7.8 was detected only through the `Indonesia` article (lead es,
  6 languages, at 22:00, the first full hour after the 21:58 origin). The quake article never formed an event.
  - Colombia M7.4 was detected first through `San José del Palmar` (12:00, es/en/it), then `Colombia`
    (13:00, 20 languages). Its article only formed an event at 00:00 (+12 h).
  - These are the pre-registered rules, so the detections count. `m65_plus_article_only` (1 / 9) is reported next to
    them, as the pre-registration requires.

## GT3

- Every 2026 World Cup knockout match except the third-place match (18 Jul) and the final (19 Jul) falls before the
  scored period. That leaves 14 excluded "out of the scored period" and n = 2, as the pre-registration anticipated.
- Wimbledon finals (11–12 Jul) are out of period. The US Open finals have no Wikipedia kick-off time, and the
  Champions League qualifiers have no match articles. All are excluded as pre-registered.
- The two matched events started 1 h and 2 h **before** kick-off (pre-match attention). Both are inside the
  pre-registered ± 3 h window.

## Consequences

- The pre-registered verdicts stand unchanged: H1b-1 rejected, H1b-2 rejected, H1b-3, H2b and H5 inconclusive.
- A future GT1 parser should take the first link to a human (P31 = Q5) item. That is a design note for the next
  pre-registration, not a change to this one.
