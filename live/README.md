---
title: Looked Up live
emoji: 🔴
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Looked Up: live layer

What editors across 30 Wikipedias are rushing to update right now (Phase 5 of
[Looked Up](https://github.com/Sbaiii/looked-up)). One connection to Wikimedia EventStreams `recentchange`; counts
only, nothing about users is stored.

- `GET /live.json`: bursts of the last 60 minutes grouped by Wikidata item, with a `status` block (`gap_minutes`
  says how much of the window is missing, e.g. after the Space slept)
- `GET /stats.json`: bursts per hour and per language over 24 h
- `GET /bursts.json?hours=72`: raw bursts (language, title, time, counts; no users)
- `GET /health`

Rules (docs/prereg_phase5.md): an article bursts at >= 5 edits by >= 3 distinct editors in 30 minutes and >= 8x its
wiki's baseline; a live event is the same item bursting in >= 2 languages within 30 minutes.
