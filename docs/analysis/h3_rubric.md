# H3 labelling rubric (fixed before labelling)

The labeller sees only the title, the language, the day and the 96 hourly **total** views (day −3 to day 0). The
desktop/mobile split and the filter's verdict are hidden (prereg §4, H3). Each unit gets one label:

- **event**: attention that a real-world occurrence plausibly explains. The rise is followed by a decay or a raised
  plateau lasting **≥ 3 hours**, usually with the daily rhythm continuing. The title is a plausible news or culture
  topic (person, match, release, disaster, place in the news, holiday).
- **non_event**: an artefact. Typical shapes:
  - an isolated 1–2 hour burst (≥ 10× the neighbouring hours) that falls straight back to the old level;
  - a regular or near-constant high plateau with no daily rhythm;
  - a target that people rarely browse to (technical, list or maintenance-like pages) with an implausible jump.
- **unsure**: neither pattern is clear.

The labeller is the project's analysis assistant (one person). The owner may re-label any row.

## Operationalisation (applied before the verdicts were joined)

To apply the rubric the same way to every unit, the shape test was written as a rule on day 0's total series,
plus one title judgement:

1. `non_event`:
   - the peak hour holds ≥ 80 % of the day's views **and** the next hour is < 5 % of the peak (an isolated burst); or
   - the target is implausible. One unit: `fr:Cookie_(informatique)`, 1.25 M views in a day on a page about HTTP cookies.
2. `event`: the peak holds ≤ 60 % of the day's views, or each of the 3 hours after the peak stays ≥ 10 % of it.
3. `unsure`: everything else.

A first attempt measured the "old level" as the median of day −1. It was discarded before labelling because quiet
articles have a median of 0–1, which made almost any burst count as an event. Each row's note in `h3_labels.csv`
shows the numbers behind its label.
