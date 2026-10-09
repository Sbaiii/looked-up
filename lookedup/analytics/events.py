"""Attention events: a QID spiking in >= N languages within any W-hour window (prereg §2).

One implementation for the warehouse, the ablation grid and production scoring. Input is a
relation of spikes with at least ``qid, lang, ts_hour_start, surprise``; output is two tables:
events (one row per event) and event_languages (one row per event and spiking language).

Interpretation of the pre-registered text (ADR 0013):

* spikes of a QID form episodes separated by >= ``new_event_gap_hours`` without spikes;
* an episode is an event if some window [t, t + W h) starting at one of its spikes holds
  spikes in >= N languages; overlapping windows merge, so there is one event per episode;
* ``start_hour`` is the earliest such window start (that window's first spike); breadth,
  peak, spread lags and excess views are measured over [start_hour, start_hour + 24 h).
"""

from __future__ import annotations

import duckdb

from lookedup.analytics.config import EventParams


def events_sql(spikes: str, p: EventParams, scored: str | None = None) -> tuple[str, str]:
    """SQL for (events, event_languages). ``scored`` (optional) is the scored-candidates relation
    used for excess views; without it excess views are summed over spike rows only."""
    gap, w, bh = p.new_event_gap_hours, p.window_hours, p.breadth_hours
    base = f"""
        WITH s AS (
            SELECT qid, lang, ts_hour_start, surprise FROM {spikes}
            WHERE qid IS NOT NULL AND surprise >= {p.r3_threshold}
        ), ordered AS (
            -- (ts_hour_start, lang) is unique within a QID: a total order keeps both windows consistent
            SELECT *, lag(ts_hour_start) OVER (PARTITION BY qid ORDER BY ts_hour_start, lang) AS prev_ts FROM s
        ), episodes AS (
            SELECT *, sum(CASE WHEN prev_ts IS NULL OR ts_hour_start - prev_ts >= INTERVAL {gap} HOUR
                               THEN 1 ELSE 0 END)
                      OVER (PARTITION BY qid ORDER BY ts_hour_start, lang ROWS UNBOUNDED PRECEDING) AS episode
            FROM ordered
        ), windows AS (
            SELECT a.qid, a.episode, a.ts_hour_start AS window_start, count(DISTINCT b.lang) AS n_langs
            FROM episodes a JOIN episodes b
              ON a.qid = b.qid AND a.episode = b.episode
             AND b.ts_hour_start >= a.ts_hour_start AND b.ts_hour_start < a.ts_hour_start + INTERVAL {w} HOUR
            GROUP BY ALL
        ), starts AS (
            SELECT qid, episode, min(window_start) AS start_hour FROM windows
            WHERE n_langs >= {p.min_languages} GROUP BY ALL
        ), members AS (
            SELECT st.qid, st.episode, st.start_hour, e.lang, e.ts_hour_start, e.surprise
            FROM starts st JOIN episodes e ON e.qid = st.qid AND e.episode = st.episode
             AND e.ts_hour_start >= st.start_hour AND e.ts_hour_start < st.start_hour + INTERVAL {bh} HOUR
        ), per_lang AS (
            SELECT qid, start_hour, lang, min(ts_hour_start) AS first_spike, max(surprise) AS peak_surprise,
                   count(*) AS spike_hours
            FROM members GROUP BY ALL
        ), lead AS (
            SELECT qid, start_hour, min(lang) AS lead_lang  -- among the max-surprise first spikes: alphabetical
            FROM (SELECT * FROM members m WHERE m.ts_hour_start = m.start_hour
                  QUALIFY surprise = max(surprise) OVER (PARTITION BY qid, start_hour)) t
            GROUP BY ALL
        )"""
    excess_src = scored or spikes
    excess = f"""
        excess AS (
            SELECT pl.qid, pl.start_hour, pl.lang,
                   sum(greatest(x.views - x.baseline_median, 0)) AS excess_views
            FROM per_lang pl JOIN {excess_src} x ON x.qid = pl.qid AND x.lang = pl.lang
             AND x.ts_hour_start >= pl.start_hour AND x.ts_hour_start < pl.start_hour + INTERVAL {bh} HOUR
            GROUP BY ALL
        )"""
    langs = base + "," + excess + """
        SELECT 'Q' || pl.qid || '@' || strftime(pl.start_hour, '%Y%m%dT%H') AS event_id,
               pl.qid, pl.start_hour, pl.lang, pl.first_spike,
               date_diff('hour', pl.start_hour, pl.first_spike) AS spread_lag_hours,
               pl.peak_surprise, pl.spike_hours, coalesce(ex.excess_views, 0) AS excess_views,
               pl.lang = ld.lead_lang AS is_lead
        FROM per_lang pl
        JOIN lead ld USING (qid, start_hour)
        LEFT JOIN excess ex USING (qid, start_hour, lang)
    """
    # ADR 0021: tier by breadth, highest threshold first
    tier_sql = "CASE " + " ".join(f"WHEN count(*) >= {n} THEN '{name}'" for name, n in p.tiers) + " END AS tier"
    events = f"""
        WITH el AS ({langs})
        SELECT event_id, qid, start_hour,
               any_value(lang) FILTER (WHERE is_lead) AS lead_lang,
               count(*) AS breadth,
               max(peak_surprise) AS peak_intensity,
               sum(excess_views) AS excess_views,
               median(spread_lag_hours) FILTER (WHERE NOT is_lead) AS median_spread_lag_hours,
               max(spread_lag_hours) AS max_spread_lag_hours,
               list(lang ORDER BY spread_lag_hours, lang) AS languages,
               -- ADR 0019: share of excess views held by the lead language
               coalesce(sum(excess_views) FILTER (WHERE is_lead) / nullif(sum(excess_views), 0), 0) AS lead_excess_share,
               CASE WHEN coalesce(sum(excess_views) FILTER (WHERE is_lead) / nullif(sum(excess_views), 0), 0)
                         >= {p.single_language_share} THEN 'single_language' ELSE 'multi_language' END AS event_class,
               {tier_sql}
        FROM el GROUP BY event_id, qid, start_hour
    """
    return events, langs


def build_events(con: duckdb.DuckDBPyConnection, spikes: str, p: EventParams,
                 scored: str | None = None) -> tuple[duckdb.DuckDBPyRelation, duckdb.DuckDBPyRelation]:
    """Relations (events, event_languages) for the spikes in relation ``spikes``."""
    ev, el = events_sql(spikes, p, scored)
    return con.sql(ev), con.sql(el)
