# 0035 — Exploring a day in the app: client-side filters, no new exports

- Status: accepted
- Date: 2026-10-22

## Context

A day file lists up to a few hundred events, but the app only offered a tier filter and pages of 12 cards.
Visitors had no way to find one event by name, to see the events of one category or language, to read a spread as
numbers, or to take the data away. The app is static (GitHub Pages) and reads the day files from the Hub
(ADR 0022), and the pipeline's exports should not grow for this.

## Decision

- **Everything works on the day file already loaded**, in `app/js/filters.js` (pure, unit-tested in node):
  search (labels in every language, descriptions, Q-number; case and accents ignored), tier, category and language
  filters, and five orders. No new export, no new request.
- **Filters are not part of the URL.** Links keep naming a day and an event (ADR 0022 links never change meaning).
  A link to an event that the current filters would hide clears those filters, so the event always shows.
- **The spread table** sits under the cards, not under the map: the map column is sticky and would cover it. Its
  headings sort the rows (again to reverse).
- **Clear filters** appears whenever a filter or the search is on and resets them all; the card order is the one
  choice remembered between visits (local storage).
- **Share** uses the browser's share sheet where there is one (phones mostly); elsewhere only Copy link shows.
- **The CSV download** is built in the browser from the same day file (RFC 4180, UTF-8 with a BOM), one row per
  event, names in the interface language.
- **Keyboard:** ← → days, J K events, T today, / search, Escape clears the search. Keys never act while the visitor
  types in a field or holds a modifier, and the help line is hidden on touch screens.

## Consequences

- No pipeline or Hub change; the features work on archive days as well as on the slider's 90 days.
- Filters reset when the page is reloaded, by design.
