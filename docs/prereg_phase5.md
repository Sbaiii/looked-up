# Phase 5 pre-registration: the live editing layer and its lead time over reading

- Registered: 2026-10-10, **before any Phase 5 code existed and before any revision history or live stream was
  collected** (git timestamp). Earlier pre-registrations and `config/analytics.yml` are unchanged.
- Any change below after data is seen is a deviation and goes in an ADR.

## Edit filter (live stream and backtest alike)

An edit counts if all of these hold:

- It is on one of **our 30 Wikipedias** (`config/languages.yml`, top 30) and in **namespace 0**.
- In the live stream: `type ∈ {edit, new}` and `bot = false`. In the backtest, from the API: revisions by accounts
  whose name ends in "bot" (case-insensitive) are dropped.
- Its comment **does not match** the maintenance patterns in `live/lookedup_live/filters.py` (`MAINTENANCE`, fixed
  now). The backtest also drops revisions tagged `mw-reverted`, `mw-rollback`, `mw-undo` or `mw-manual-revert`.
  - Patterns: revert, undo, rollback, `rv `, "reverted edits", "undid revision", the AWB / HotCat / Twinkle / huggle /
    IABot / InternetArchiveBot / WPCleaner tool tags, `{{` maintenance-template-only edits, and "typo" / "fix typo"
    / "copyedit".
- **Nothing about users is stored.** Distinct editors are counted from a salted hash held only for the window it
  belongs to.

## Edit burst

- **Window rule.** At edit time *t*, the article's last 30 minutes (*t* − 30 min, *t*] hold **≥ 5 counted edits by
  ≥ 3 distinct editors**. In addition, `2 × edits(30 min)` must be **≥ 8 ×** the wiki's per-article baseline.
- **Baseline:** the median edits per article-hour, over articles edited in that hour, across the wiki's last 7 days
  of its own live history.
  - Before 24 h of history it is the **conservative default 1.0** (the observed median of edited articles is 1 in
    every large wiki), so the 5-edit rule dominates.
  - The backtest has no live history and uses the default.
- **New-article rule.** A page created (`type = new`, or the first revision in the backtest) and edited **≥ 5 times
  in its first 60 minutes** bursts at its 5th edit.
- **Burst time:** the time of the edit that first satisfies the rule.
- **Live event:** one QID bursting in **≥ 2 languages within 30 minutes**. Its time is the second language's burst
  time.

## H9: edits lead reading

- **Population.** Multi-language product events (ADR 0021) with `start_hour` in the **30 days ending 9 Oct 2026
  23:00 UTC** (10 Sep – 9 Oct), from the warehouse refreshed to 9 Oct (Step 4).
  - At most **2,000 events**, taking the widest first (breadth, then excess views).
- **Edit data.** Revisions from the MediaWiki API for the event's article in the **lead language** and up to **4
  other languages**, in spread order, within [`start_hour` − 48 h, `start_hour` + 24 h].
- **Burst time.** The earliest burst under the rule above in any fetched language, within [`start_hour` − 24 h,
  `start_hour` + 24 h]. Events without one are counted and reported but excluded from the lead-time distribution.
- **Lead time** = `start_hour` − burst time, in minutes. `start_hour` is the beginning of the first spiking hour.
  A positive lead means editors burst before that hour began.
- **H9** is **supported** if the median lead time ≥ **60 minutes**. Reported alongside: the IQR, the share of
  events with a burst, the share with lead > 0, and the lead time by category (descriptive).

## H10: multi-language edit bursts predict reading events

- **Units.** Live events (≥ 2 languages within 30 min) collected by the live consumer, each with a QID.
- **Hit.** The lake's product events contain an event on the same QID with `start_hour` in [floor_hour(*b*) − 2 h,
  floor_hour(*b*) + 24 h], where *b* is the live event's time.
- **Precision** = hits / live events. Reported alongside:
  - the **base rate**: the same hit rate for single-language edit bursts collected in the same windows;
  - the forward-only precision (`start_hour` ≥ floor_hour(*b*)).
- **H10** is **supported** if precision ≥ **30 %** with ≥ **100** scored live events.
- With fewer than 100 scored live events, H10 is **inconclusive**. The scoring then accumulates automatically: a
  daily job scores the live events of two days earlier, once their 24 h of pageviews have arrived, until 100 are
  scored. The report states how many days that needs.
- A live event can be scored only after floor_hour(*b*) + 24 h + ≈ 3 h of dump lag.
