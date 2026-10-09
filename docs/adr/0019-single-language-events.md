# 0019 — Single-language events (no censoring)

- Status: accepted; adds to ADR 0015 without changing the pre-registered rule
- Date: 2026-10-09

## Context

Phase 2's clearest false positive, `ja:膣内射精`, passed the 3-language rule with co-spikes in English (surprise 50)
and Chinese (31), against 6,534 in Japanese. Two possible fixes were considered:

- **"Each language needs its own surprise ≥ 8"** is *already* the rule: each language-hour is filtered by R3 before
  languages are counted (`events_sql`, `test_low_surprise_spikes_are_ignored`). Requiring it again changes nothing.
- **An entity blocklist** (adult topics, namespaces) is rejected. Looked Up measures attention; it does not censor topics.

## Decision

Every event gets `lead_excess_share`, the lead language's share of the event's excess views. Events with a share
**≥ 0.95** are classified **`single_language`**. They are kept everywhere, but listed separately: a separate list in
`data/latest.json`, and the `event_class` column in the warehouse and lake. The threshold is in
`config/analytics_v2.yml`; the registered `config/analytics.yml` is unchanged.

## Effect on the 90-day batch (docs/analysis/a4_reclassification.json)

- **The event set is unchanged** (the same 11,127 event IDs). **511 events (4.6 %) become `single_language`**, so
  10,616 remain multi-language.
- The false positive is reclassified (share 0.988), as are 2 of the 5 unverified non-portal events (Case Keenum,
  Perez Hilton).
- Real one-community events are classified the same way: Yuri Nakamura's death (ja, 0.981), Haruka Fukuhara's
  marriage (ja, 0.978). "Single-language" means "attention from one community", not "false".
- By lead language: en 379, it 35, de 32, ja 30, fr 18. Median breadth 3 (max 10).
