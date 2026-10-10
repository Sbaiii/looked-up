"""Snapshot features at decision time (docs/prereg_phase4.md), one SQL implementation for the warehouse
(fct_event_snapshots) and for live scoring (lookedup.forecast.predict).

Inputs (relation names):

* ``events``: event_id, qid, start_hour, lead_lang, breadth, event_class, category (product events, ADR 0021)
* ``spikes``: candidate rows (R1 or R2, surprise >= 6, not automated, with a QID):
  qid, lang, title, ts_hour_start, surprise, views, baseline_median
* ``views``: article-hours with >= 100 views: lang, title, ts_hour_start, views (+ baseline_median for targets)
* ``dims``: qid, entity_class, n_languages

t0 is the detection hour (the second language's first spike, R3 >= 8); snapshots at t0 + k for k in offsets,
kept while T < start_hour + 24 h. Every feature uses rows with ts_hour_start <= T only.
"""

from __future__ import annotations

R3 = 8.0
OFFSETS = (0, 1, 3)
FADE_CAP = 48
PEAK_HORIZON = 72

NUMERIC = ["breadth_t", "max_surprise_t", "sum_surprise_t", "excess_t", "lead_share_t", "new_langs_last_hour",
           "hours_since_start", "is_death", "hour_utc", "weekday", "n_sitelinks", "views_t", "views_slope",
           "peak_views_so_far", "lead_views_share"]
CATEGORICAL = ["lead_lang", "entity_class"]
FEATURES = NUMERIC + CATEGORICAL
MONOTONE_UP = {"breadth_t", "max_surprise_t", "sum_surprise_t", "excess_t", "n_sitelinks"}
LEAKY = {"n_sitelinks", "is_death"}       # declared leakage risks (sensitivity model without them)
AUXILIARY = ["excess_hour_t", "hours_since_peak"]   # baseline inputs, not model features


def snapshot_sql(events: str, spikes: str, views: str, dims: str, offsets=OFFSETS, targets: bool = False,
                 data_end: str | None = None) -> str:
    offs = ", ".join(f"({k})" for k in offsets)
    target_ctes = ""
    target_cols = ""
    target_joins = ""
    if targets:
        end = f"TIMESTAMP '{data_end}'" if data_end else "TIMESTAMP '9999-01-01'"
        target_ctes = f""",
        grid AS (   -- dense hourly totals of every spiking article of the event, [start, start + {PEAK_HORIZON} h]
            SELECT e.event_id, e.start_hour + to_hours(h.i) AS ts
            FROM ev e, range(0, {PEAK_HORIZON + 1}) h(i)
        ), tot AS (
            SELECT g.event_id, g.ts, coalesce(sum(v.views), 0) AS views, coalesce(sum(v.ex), 0) AS ex
            FROM grid g LEFT JOIN vt v ON v.event_id = g.event_id AND v.ts_hour_start = g.ts
            GROUP BY ALL
        ), peak AS (
            SELECT event_id, max(views) AS peak, arg_max(ts, views) AS peak_ts FROM tot GROUP BY ALL
        ), nxt AS (
            SELECT s.event_id, s.k, sum(t.ex) AS excess_next24
            FROM snaps s JOIN tot t ON t.event_id = s.event_id AND t.ts > s.T AND t.ts <= s.T + INTERVAL 24 HOUR
            GROUP BY ALL
        ), fd AS (
            SELECT s.event_id, s.k, min(t.ts) AS fade_ts
            FROM snaps s JOIN peak p ON p.event_id = s.event_id
            JOIN tot t ON t.event_id = s.event_id AND t.ts >= greatest(s.T, p.peak_ts) AND t.views < p.peak / 2
            GROUP BY ALL
        ), tgt AS (
            SELECT s.event_id, s.k, nx.excess_next24, f.fade_ts, s.T + INTERVAL {FADE_CAP} HOUR <= {end} AS fade_observable
            FROM snaps s LEFT JOIN nxt nx ON nx.event_id = s.event_id AND nx.k = s.k
            LEFT JOIN fd f ON f.event_id = s.event_id AND f.k = s.k
        )"""
        target_cols = f""",
               (e.breadth >= 5)::INT AS reach_international, (e.breadth >= 20)::INT AS reach_planetary,
               coalesce(tg.excess_next24, 0) AS excess_next24,
               least(coalesce(date_diff('hour', s.T, tg.fade_ts), {FADE_CAP}), {FADE_CAP}) AS fade_hours,
               tg.fade_observable"""
        target_joins = "LEFT JOIN tgt tg ON tg.event_id = s.event_id AND tg.k = s.k"
    return f"""
        WITH ev AS (
            SELECT event_id, qid, start_hour, lead_lang, breadth, category FROM {events}
            WHERE event_class = 'multi_language'
        ), sp AS (      -- candidate rows of the event's episode (start .. start + 24 h)
            SELECT e.event_id, s.lang, s.title, s.ts_hour_start, s.surprise,
                   greatest(s.views - s.baseline_median, 0) AS ex
            FROM ev e JOIN {spikes} s ON s.qid = e.qid
             AND s.ts_hour_start >= e.start_hour AND s.ts_hour_start < e.start_hour + INTERVAL 24 HOUR
        ), firsts AS (
            SELECT event_id, lang, min(ts_hour_start) AS first_spike FROM sp WHERE surprise >= {R3} GROUP BY ALL
        ), det AS (     -- t0: the second language's first spike
            SELECT event_id, list(first_spike ORDER BY first_spike)[2] AS t0 FROM firsts
            GROUP BY event_id HAVING count(*) >= 2
        ), snaps AS (
            SELECT e.event_id, e.qid, e.start_hour, e.lead_lang, e.category, d.t0, o.k, d.t0 + to_hours(o.k) AS T
            FROM ev e JOIN det d USING (event_id) CROSS JOIN (VALUES {offs}) o(k)
            WHERE d.t0 + to_hours(o.k) < e.start_hour + INTERVAL 24 HOUR
        ), agg AS (
            SELECT s.event_id, s.k,
                   count(DISTINCT p.lang) FILTER (WHERE p.surprise >= {R3}) AS breadth_t,
                   max(p.surprise) FILTER (WHERE p.surprise >= {R3}) AS max_surprise_t,
                   sum(p.surprise) FILTER (WHERE p.surprise >= {R3}) AS sum_surprise_t,
                   sum(p.ex) AS excess_t,
                   sum(p.ex) FILTER (WHERE p.lang = s.lead_lang) AS lead_ex,
                   coalesce(sum(p.ex) FILTER (WHERE p.ts_hour_start = s.T), 0) AS excess_hour_t
            FROM snaps s JOIN sp p ON p.event_id = s.event_id AND p.ts_hour_start <= s.T
            GROUP BY ALL
        ), newl AS (
            SELECT s.event_id, s.k, count(*) AS new_langs_last_hour
            FROM snaps s JOIN firsts f ON f.event_id = s.event_id AND f.first_spike = s.T GROUP BY ALL
        ), titles AS (  -- articles that spike (R3) in the episode; known at T once their first spike is <= T
            SELECT event_id, lang, title, min(ts_hour_start) AS known_from FROM sp WHERE surprise >= {R3} GROUP BY ALL
        ), vt AS (
            SELECT t.event_id, t.lang, t.known_from, v.ts_hour_start, v.views
                   {", greatest(v.views - v.baseline_median, 0) AS ex" if targets else ""}
            FROM titles t JOIN ev e USING (event_id)
            JOIN {views} v ON v.lang = t.lang AND v.title = t.title
             AND v.ts_hour_start >= e.start_hour AND v.ts_hour_start <= e.start_hour + INTERVAL {PEAK_HORIZON} HOUR
        ), vsnap AS (   -- hourly totals of the articles known at T, hours <= T
            SELECT s.event_id, s.k, v.ts_hour_start, sum(v.views) AS views,
                   sum(v.views) FILTER (WHERE v.lang = s.lead_lang) AS lead_views
            FROM snaps s JOIN vt v ON v.event_id = s.event_id AND v.known_from <= s.T AND v.ts_hour_start <= s.T
            GROUP BY ALL
        ), vfeat AS (
            SELECT s.event_id, s.k,
                   coalesce(max(v.views) FILTER (WHERE v.ts_hour_start = s.T), 0) AS views_t,
                   ln(1 + coalesce(max(v.views) FILTER (WHERE v.ts_hour_start = s.T), 0))
                     - ln(1 + coalesce(max(v.views) FILTER (WHERE v.ts_hour_start = s.T - INTERVAL 2 HOUR), 0)) AS views_slope,
                   coalesce(max(v.views), 0) AS peak_views_so_far,
                   coalesce(sum(v.lead_views) / nullif(sum(v.views), 0), 0) AS lead_views_share,
                   coalesce(date_diff('hour', arg_max(v.ts_hour_start, v.views), s.T), 0) AS hours_since_peak
            FROM snaps s LEFT JOIN vsnap v ON v.event_id = s.event_id AND v.k = s.k
            GROUP BY s.event_id, s.k, s.T
        ){target_ctes}
        SELECT s.event_id || '#' || s.k AS snapshot_id, s.event_id, s.qid, s.k AS offset_h, s.start_hour, s.t0,
               s.T AS snapshot_ts, s.lead_lang, coalesce(d.entity_class, 'other') AS entity_class,
               coalesce(a.breadth_t, 0) AS breadth_t, coalesce(a.max_surprise_t, 0) AS max_surprise_t,
               coalesce(a.sum_surprise_t, 0) AS sum_surprise_t, coalesce(a.excess_t, 0) AS excess_t,
               coalesce(a.lead_ex / nullif(a.excess_t, 0), 0) AS lead_share_t,
               coalesce(n.new_langs_last_hour, 0) AS new_langs_last_hour,
               date_diff('hour', s.start_hour, s.T) AS hours_since_start,
               (s.category = 'death')::INT AS is_death, hour(s.T) AS hour_utc, isodow(s.T) - 1 AS weekday,
               coalesce(d.n_languages, 0) AS n_sitelinks,
               vf.views_t, vf.views_slope, vf.peak_views_so_far, vf.lead_views_share,
               coalesce(a.excess_hour_t, 0) AS excess_hour_t, vf.hours_since_peak, s.category{target_cols}
        FROM snaps s
        LEFT JOIN agg a ON a.event_id = s.event_id AND a.k = s.k
        LEFT JOIN newl n ON n.event_id = s.event_id AND n.k = s.k
        LEFT JOIN vfeat vf ON vf.event_id = s.event_id AND vf.k = s.k
        LEFT JOIN {dims} d ON d.qid = s.qid
        {"JOIN ev e ON e.event_id = s.event_id" if targets else ""}
        {target_joins}
    """
