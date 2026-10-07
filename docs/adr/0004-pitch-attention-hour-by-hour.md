# 0004 — Pitch: what the world pays attention to, hour by hour, across languages

- Status: accepted (project owner decision D1)
- Date: 2026-10-08
- Evidence: [feasibility §5](../feasibility.md)

## Context

The original pitch ("events before the news") did not survive Phase 0. Pageview spikes start in the same hour as the
event, and the hourly dumps publish ≈ 2.2 h after the hour ends. Editors react within 1–30 minutes.

## Decision

Looked Up measures **what the world pays attention to, hour by hour, across languages**.

- **Pageviews** measure attention: how much, in which languages, how it spreads and how long it lasts.
- **Edits** (EventStreams) are the fast signal. They are a later phase, not part of ingestion v1.

## Consequences

- README, UI copy and the daily briefing describe the last few hours and never promise "before the news".
- The ingestion pipeline is designed around hourly completeness and correctness, not seconds of latency.
