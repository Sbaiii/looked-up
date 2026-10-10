# 0024 — Hero selection: excess views, a strength floor and widening windows

- Status: accepted (replaces the v1 rule "the widest event of the last 24 h")
- Date: 2026-10-10

## Context

v1 put `today.json`'s widest event in the hero. On a quiet day that was "Zodiac": 4 languages and 13,288 extra
views, too weak to lead the page.

## Decision

- **Rank** multi-language events by **total excess views**, breaking ties by breadth. Single-language events never
  lead.
- **Qualify:** an event can lead only with **≥ 100,000 excess views**, or at tier **international** or above
  (ADR 0021).
- **Widen** if nothing in the last 24 h qualifies:
  - first to **48 h**, with the kicker "LAST 48 HOURS";
  - then to **7 days**, with the kicker "THIS WEEK";
  - if nothing qualifies even then, the hero says nothing has spread yet.
- **Day view:** the same rule picks the default selected event. If nothing qualifies, it selects the day's top-ranked
  event anyway.
- **Briefing:** the lead sentence uses the same ranking.
- **Where it lives:** `app/js/select.js`, mirrored in `lookedup/og.py` for the social cards. Tests:
  - `tests/app/unit/select.test.mjs`, with fixtures for the quiet-day, 48-hour, week and busy-day cases;
  - `tests/test_og.py`.
- **Exports:** day and today files now also keep the top 20 events by excess views (ADR 0022). A big two-language
  event can therefore never be missing from the ranking.

## Consequences

- The hero can show an event from yesterday or earlier this week. The kicker says which window it came from.
- Widening loads up to seven earlier day files. They're cached and only needed on quiet days.
