# 0005 — Store desktop and mobile views as separate columns

- Status: accepted (project owner decision D2). Supersedes the "desktop and mobile summed" part of ADR 0001.
- Date: 2026-10-08
- Evidence: [feasibility §1c, §2a](../feasibility.md)

## Context

Human Wikipedia traffic is ≈ 56 % mobile (88 % fa, 45 % de). Automated traffic that passes the `user` classifier is
almost all desktop. Examples: *Cookie_(informatique)* (624 k views/day on fr) and `Special:RecentChanges` polling.

## Decision

Every hourly row carries `views_desktop` and `views_mobile` (mobile web and apps, `xx.m` in the hourly dumps,
`mobile-web` + `mobile-app` in `pageview_complete`). We never store a pre-summed total.

## Consequences

- The mobile share is available downstream as a human-vs-bot signal for every article and hour.
- The retention threshold applies to the sum (ADR 0007). Totals are computed at query time.
- The cost is about 17 % more rows than the summed variant measured in Phase 0. We accept it.
