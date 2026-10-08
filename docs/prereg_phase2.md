# Phase 2 pre-registration: attention events across languages

- Registered: 2026-10-08, **before any analytics code is written or any result is seen**.
- Git history is the timestamp: this file and `config/analytics.yml` are committed before `warehouse/`, the evaluation
  code or any output exists.
- Thresholds live in [`config/analytics.yml`](../config/analytics.yml). The values committed with this document are
  the **primary configuration**. Hypotheses are judged on the primary configuration only.
- Any later change to a definition, threshold, metric or protocol is a **deviation**. Deviations are allowed, but each
  one must be logged in an ADR and in the results document, with the reason and with results under both the
  registered and the changed version. Nothing is changed silently.

## 1. Data and period

- Source: the Looked Up lake (`Sbaiiiiii/looked-up`). Hourly article views for 30 Wikipedias, desktop and mobile
  separate, rows kept when views ≥ 5 per hour (ADR 0007).
- Period: **2026-07-09 00:00 to 2026-10-07 23:00 UTC** (91 days).
- **Warm-up:** baselines need history, so detection and evaluation start on **2026-07-16**. The first 7 days only feed
  baselines. The evaluation period is 2026-07-16 to 2026-10-07 (84 days).
- **Absent rows:** a missing (lang, title, hour) means fewer than 5 views. It is imputed as **0** in every computation
  (baselines, ratios, excess views). This slightly under-estimates quiet baselines and favours spike detection for
  small articles. The floors below (≥ 100 views) limit the effect.
- **Completeness gate:** analysis starts only if the manifest has ≥ 98 % of the hours in the period. Missing hours are
  listed in the results and treated as absent (not imputed).

## 2. Definitions

### Unit of analysis

`(lang, entity, hour)`. `entity` is the Wikidata QID from `data/wikidata/sitelinks.parquet`, joined on
`(lang, title)`. Titles without a QID keep a synthetic key `lang:title`. They can spike in one language, but by
construction they cannot form multi-language events.

### Automation filter

A `(lang, title, day)` is `is_automated` if **either**:

- (a) day views ≥ **500** and mobile share < **5 %**; or
- (b) the hourly series is **flat**: coefficient of variation of hourly views over the day < **0.15**, with mean
  views ≥ **200 per hour**. This is a crawler signature: humans follow a daily cycle, crawlers do not.

Flagged rows are **kept** in the lake and in the warehouse. They are **excluded from spike detection** and ranked
separately.

Trade-off: a real event that only desktop users follow (some workplace-hour news in a desktop-heavy language), or a
steady real interest, can be wrongly flagged. We accept that recall loss in exchange for removing the largest
source of false "events" seen in Phase 0 and Phase 1 (e.g. `fr:Cookie_(informatique)`: 40 k views/hour at 0.6 % mobile).

### Baseline

For each `(lang, entity, hour-of-day, day type)`, where day type is weekday (Mon–Fri) or weekend (Sat–Sun):
the **median** and **MAD** of views over the **previous 28 days**, strictly before the day being scored. It
requires **≥ 7 observations**. The fallbacks, in order:

1. `(lang, entity, hour-of-day)` over the previous 28 days, ≥ 7 observations;
2. the **language-level prior**: median and MAD of hourly views over all article-hours of that language in the
   previous 28 days, restricted to entities seen on ≥ 7 distinct days. This applies to unseen or brand-new entities.

An entity scored with the language prior is **"unseen"**. Unseen entities may spike only under R2 + R3, never R1
(yesterday's value of a brand-new article is meaningless).

### Spike rules

For an article-hour with `views` (desktop + mobile):

- **R1** (day over day): `views ≥ 5 × views(same hour, previous day)` and `views ≥ 100`.
- **R2** (hour over hour): `views ≥ 3 × median(views of the previous 3 hours)` and `views ≥ 100`.
- **R3** (surprise): `s = (views − baseline_median) / (1.4826 × MAD + sqrt(baseline_median) + 1) ≥ 8`.

An article-hour **spikes** if **R3 and (R1 or R2)**. For unseen entities: **R3 and R2**. Automated
`(lang, title, day)` rows never spike.

### Attention event

A QID with spikes in **≥ 3 languages** within **any 6-hour window**. Overlapping qualifying windows of the same QID
merge into one event. A new event for the same QID needs a gap of ≥ 24 h without spikes.

| Attribute | Definition |
|---|---|
| `start_hour` | hour of the first spike (any language) in the event |
| `lead_lang` | language of that first spike; ties broken by the highest surprise score, then alphabetically |
| `breadth` | number of distinct languages spiking within 24 h of `start_hour` |
| `peak_intensity` | max surprise score `s` over the event's spikes |
| `excess_views` | sum over languages and over the 24 h from `start_hour` of `max(0, views − baseline_median)` |
| `spread_lag[lang]` | hours from `start_hour` to that language's first spike (0 for the lead) |
| `category` | coarse class (§2, next) |

### Category

From Wikidata: P31 (instance of), and P106 (occupation) for humans, mapped to coarse classes listed in
`config/analytics.yml`: `death`, `human`, `sports`, `entertainment`, `disaster`, `politics`, `place`,
`organization`, `science_tech`, `other`.

- A human whose P570 (date of death) falls within **7 days before `start_hour`** up to **1 day after** is `death`.
  P570 is fetched from the Wikidata API at analysis time.
- Other humans are `sports` or `entertainment` if their P106 matches the lists in the config, else `human`.
- When several P31 values map to different classes, the first match in the config's priority order wins.

## 3. Ground truth (Wikipedia Portal:Current events)

- Daily pages `Portal:Current_events/2026_<Month>_<D>` for 2026-07-09 to 2026-10-07, fetched as wikitext via the
  MediaWiki API.
- **Entry** = one bullet. Fields: date, section heading (the portal's own category, e.g. "Disasters and accidents",
  "Sports", "Armed conflicts and attacks"), the wikilinks in the bullet text (sources are external links, so they
  are not wikilinks).
- Linked titles are resolved to QIDs (following redirects) via the API.
- **Generic entities excluded:** QIDs whose P31 is in `generic_classes` in the config (countries, sovereign states,
  continents, oceans, international organisations, capital cities). They are linked from countless bullets and would
  give free credit.
- **Major (date, QID) pair** = a non-generic QID linked in an entry on that date that has sitelinks in **≥ 3 of our
  30 languages**. The unit of H1 recall is the (date, QID) pair; duplicate pairs on the same day count once.

## 4. Hypotheses, metrics and rejection criteria

### H1. Detection of major Current Events entries

- **Claim:** the rule detects **≥ 70 %** of major (date, QID) pairs **within 6 h**.
- **Detected within 6 h:** an attention event for that QID with `start_hour` in
  `[date 00:00 − 6 h, date 23:59 + 6 h]`. The portal has day granularity, so ±6 h around the calendar day.
  **Within 24 h** uses ±24 h.
- **Primary metric:** `recall_6h` = detected pairs / major pairs, over the evaluation period.
- **Reject H1 if** `recall_6h < 0.70`. `recall_24h` is reported, but H1 is judged on 6 h only.

### H2. Lead language = language of the event's country

- **Geolocatable event:** a detected event, matched to a portal entry, whose QID (or, if missing, its P276 location)
  has a P17 country with at least one official language (P37) among our 30. P37 values map to our codes in the config.
- **Claim:** `lead_lang` is an official language of that country in **≥ 60 %** of geolocatable events.
- **Reject H2 if** the share is < 0.60.
- **Pre-registered context:**
  - (i) the same share **excluding countries where English is official**;
  - (ii) the base rate, the share of all events whose `lead_lang` is `en`.

  If H2 holds only because of English-official countries, the results say so.

### H3. Automation filter removes non-events

- **Pool:** article-hours that satisfy the spike rule when the automation filter is **switched off**, over the
  evaluation period. Rank them by surprise score and keep the top 1,000 `(lang, title, day)` units.
- **Sample:** 100 units drawn at random from the pool (seed `20261008`).
- **Labelling, blind:** each unit is labelled `event`, `non_event` or `unsure`. The labeller sees the title, the
  language, and the hourly total-views series for that day and the 3 days before. The labeller does **not** see the
  desktop/mobile split or the filter's verdict, because those are the filter's own inputs.
  - Labels are written to `docs/analysis/h3_labels.csv` and **committed before** the filter's verdicts are joined.
  - The labeller is the analyst (this project's assistant), so this is a judgement audit, not an independent panel.
    The owner may re-label any row; disagreements will be reported.
- **Metric:** among units labelled `non_event`, the share the filter flags as `is_automated`.
- **Claim:** ≥ **90 %**. **Reject H3 if** < 0.90. If fewer than 20 units are labelled `non_event`, H3 is
  **inconclusive**: the filter has little to remove in this sample.
- **Also reported:** the share of `event` units wrongly flagged, which is the filter's recall cost.

### H4. Spread is faster for deaths and disasters than for sports and entertainment

- **Per event:** `median_lag` = median `spread_lag` over its non-lead languages, within 24 h.
- **Groups:** A = `death` ∪ `disaster`; B = `sports` ∪ `entertainment`. Primary configuration, all detected events in
  the evaluation period.
- **Claim:** `median(median_lag | A) < median(median_lag | B)`, tested with a one-sided Mann–Whitney U test at
  α = 0.05.
- **Reject H4 if** p ≥ 0.05, or if the medians go in the opposite direction. If either group has < 10 events, H4 is
  **inconclusive**.

## 5. Secondary metrics (descriptive, no thresholds)

- **Detection delay:** for major pairs with a known timestamp, `start_hour − event time` (floored to the hour).
  Timestamp sources, in order:
  - an infobox time field with a UTC or offset time;
  - else the first revision of an event article created within ±2 days of the entry date.

  Otherwise the pair is skipped. Reported as a distribution (median, IQR, share ≤ 6 h).
- **Precision proxy:** share of detected events whose QID appears in the portal (any entry, generic or not) within
  ±2 days of `start_hour`. All other events are listed for review.
- **Non-portal check:** the **30 largest** detected events (by `excess_views`) that are not in the portal are checked
  by hand and labelled `real` (a real-world occurrence explains it) or `not_real`. A high share of `real` events here
  is evidence that the English-centric portal misses non-English events.
- **Per-category recall** (portal section headings), and **per-language lead counts**.
- Number of events, and the breadth distribution.

## 6. Ablations (reported in full; hypotheses use the primary config only)

| Parameter | Values | Primary |
|---|---|---|
| R3 threshold | 6, 8, 12 | 8 |
| Minimum languages | 2, 3, 5 | 3 |
| Window | 3 h, 6 h, 12 h | 6 h |

- That is 27 configurations. For each: event count, `recall_6h`, `recall_24h`, precision proxy.
- **"Winner"**, defined now: the configuration with the highest harmonic mean of `recall_24h` and precision proxy.
  The winner is reported but does **not** replace the primary configuration for the hypothesis verdicts.

## 7. Known biases, declared in advance

- **The portal is English-centric** and editor-curated. Recall measures detection of English-visible news.
  Precision is a proxy: a detected event missing from the portal is not necessarily false (see the non-portal check).
- **Day granularity:** the portal gives dates, not times, so recall windows are around calendar days in UTC. Events
  late in the UTC day may be listed on the next day.
- **Retention floor:** articles under 5 views per hour are invisible. Small-language attention to minor topics is undercounted.
- **Thirty languages only:** "breadth" is breadth among these 30, which over-represent Europe and East Asia.
- **Bots inside `user` traffic:** the automation filter is a heuristic, and H3 measures how good it is.
- **Single analyst:** labels for H3 and the non-portal check come from one labeller.
