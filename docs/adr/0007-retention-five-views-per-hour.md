# 0007 — Retention: hourly article rows with at least 5 views

- Status: accepted (project owner decision D4). Refines the retention tier of ADR 0002.
- Date: 2026-10-08
- Evidence: [feasibility §6](../feasibility.md)

## Decision

For the active languages, keep an hourly row when it is an **article** (same exclusions as ADR 0006: main page,
namespace prefixes, `-`) and `views_desktop + views_mobile >= 5`. Raw dump files are deleted right after processing.

## Consequences

- Phase 0 measured that this tier keeps ≈ 10 % of rows and ≈ 57 % of views, at ≈ 15–21 GB/year for 50 languages.
  Expect less for 30 languages.
- Long-tail articles below 5 views/hour are not stored. Any hour can be rebuilt with a different threshold from
  Wikimedia's own archive (hourly dumps since 2015, CC0).
- Spike detection must treat "absent" as "< 5 views", not as zero.
