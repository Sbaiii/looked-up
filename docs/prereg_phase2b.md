# Phase 2b pre-registration: evaluation against sudden, timestamped events

- Registered: 2026-10-09, **before any Phase 2b ground truth was fetched or any Phase 2b metric was computed** (git
  timestamp). docs/prereg_phase2.md and config/analytics.yml are unchanged.
- **Detector under test:** the Phase 2 primary configuration, unchanged (R3 ≥ 8; R1 or R2; ≥ 3 languages within a
  6-hour window; config/analytics.yml), as materialised in the warehouse table `fct_attention_events`.
  - **"Detected"** means any attention event for a target QID, whatever its `event_class` (ADR 0019: single- and
    multi-language events are both detections).
  - Results by class are reported descriptively.
- **Scored period:** events exist from 2026-07-16 00:00 to 2026-10-07 23:00 UTC. A ground-truth item counts only if
  its **whole detection window** lies inside the scored period. Other items are listed as "out of window".
- Any change to these definitions after data is seen is a deviation and goes in an ADR.

## Ground truths

### GT1: deaths

- **Source:** the English Wikipedia lists "Deaths in July 2026", "Deaths in August 2026" and "Deaths in September 2026"
  (wikitext via the MediaWiki API).
- **Parsing:** each bullet under a day heading is one death. The target is the **first wikilink** of the bullet,
  resolved to a QID (redirects followed). The reference day **D** is the heading's day.
- **Inclusion:** the QID has sitelinks in **≥ 5 of our 30 languages** (data/wikidata/sitelinks.parquet).
- **Detection window (24 h):** an event for the QID with `start_hour` in `[D 00:00 − 12 h, D+1 00:00 + 24 h)`. That
  is the death day plus 24 h, with 12 h of slack before midnight UTC, because the lists use local dates.
- **Announcement proxy (secondary):** the earliest enwiki revision of the article with a timestamp in
  `[D−1 00:00, D+2 00:00)` whose edit summary matches
  `(?i)\b(death|died|dies|dead|passed away|passing|rip|deceased|dod|obituary)\b`. If none exists, the item has no
  proxy. Delay from the proxy = `start_hour − floor_hour(proxy)`.

### GT2: earthquakes

- **Source:** USGS FDSN event API
  (`https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&eventtype=earthquake&minmagnitude=6.0`),
  origin times from 2026-07-16 00:00 to 2026-10-07 18:00 UTC (so the 6 h window ends inside the period).
  Fields: origin time, magnitude, place, coordinates.
- **Targets (alternatives; detected if any target is detected):**
  - **(a) earthquake article:** a Wikidata item that is an instance (or subclass) of earthquake (Q7944), has a
    point in time (P585) within `[origin − 1 day, origin + 2 days]`, and has at least one sitelink among our 30
    languages created ≤ 48 h after the origin.
    - If several match, take the one closest to the USGS coordinates (P625); if coordinates are missing, the
      closest magnitude (P2528).
  - **(b) place articles:** the USGS `place` string is "…of LOCALITY, REGION" or just "REGION".
    - Both LOCALITY and REGION are resolved as English Wikipedia titles to QIDs (redirects followed; unresolvable
      names are dropped).
- **Detection window (6 h):** an event for a target with `start_hour` in `[floor_hour(origin), floor_hour(origin) + 6 h]`.
- **Affected country (for H2b):** the P17 country of the earthquake article. Otherwise the P17 of the REGION item, or
  the REGION itself if it is a country. Official languages are the country's P37, mapped to our codes
  (`official_languages` in config/analytics.yml).

### GT3: scheduled finals and major matches

- **Candidate matches** in the scored period:
  - 2026 FIFA World Cup knockout matches;
  - the Wimbledon and US Open singles finals;
  - UEFA Champions League qualifying matches.
- **Kick-off time:** only from Wikipedia. Either the `{{Football box}}` `|time=` field (with its UTC offset) in the
  match's article or in "2026 FIFA World Cup knockout stage", or an infobox time field. Matches without a
  Wikipedia-sourced kick-off time (tennis finals have none in their infoboxes; qualifiers have no match articles) are
  **excluded and listed**.
- **Targets:** the match article (if any) and the two teams' articles (national teams; for tennis, the two players).
  Detected if any target is detected.
- **Detection window (3 h):** an event for a target with `start_hour` in `[kick-off − 3 h, kick-off + 3 h]`.

## Hypotheses and rejection criteria

| ID | Claim | Rejected if |
|---|---|---|
| **H1b-1** | ≥ 60 % of GT1 deaths detected within their 24 h window | recall < 0.60 |
| **H1b-2** | ≥ 70 % of GT2 earthquakes of **M ≥ 6.5** detected within 6 h of origin | recall < 0.70 |
| **H1b-3** | ≥ 90 % of GT3 matches detected within 3 h of kick-off | recall < 0.90; with < 5 matches it is **inconclusive** |
| **H2b** | For detected GT2 quakes (within 24 h, any target) whose affected country has an official language among our 30, the event's lead language is one of them in ≥ 60 % of cases | share < 0.60; with < 5 qualifying quakes it is **inconclusive** |
| **H5** | Median detection delay `start_hour − floor_hour(origin)` over GT2 quakes (M ≥ 6.0) detected within 24 h is **≤ 4 h** | median > 4 h; with < 5 detected quakes it is **inconclusive** |

H5 measures the detector's own delay (pageview hours). The operational delay adds 1 h (end of the hour) plus the
≈ 2.2 h median dump lag, and is reported alongside.

## Secondary metrics (descriptive)

- GT2 recall for **M 6.0–6.5**, and for target (a) only versus targets (a) or (b).
- GT1 recall by number of languages (5–9, 10–19, ≥ 20), and delay from the announcement proxy (median, IQR).
- For every detection: breadth, lead language, `event_class`.
- Items out of window, unresolved items and excluded matches are listed with reasons.

## Single ablation (fixed now)

Minimum languages **2, 3 (primary), 5**, with R3 ≥ 8 and a 6 h window, for H1b-1/2/3 recall. Only the primary
configuration decides the verdicts.

## Known limitations, declared in advance

- **GT1 is English-centric.** The en lists cover deaths worldwide, but notability is judged by en editors.
- **GT2 targets (b) can match unrelated attention** to a region (e.g. a country article in the news for other
  reasons within 6 h). Recall with target (a) only is reported for that reason.
- **GT3 is tiny** because of the scored period (the World Cup quarter- and semi-finals and Wimbledon fall before
  2026-07-16).
- Death lists give dates, not times, so GT1 uses a day window.
