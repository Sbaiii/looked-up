"""Production scoring: daily baselines (data/baselines/) and hourly spikes/events (data/events/, latest.json).

Batch (the warehouse) and production share the SQL rules in lookedup.analytics.scoring and
the event builder in lookedup.analytics.events. Two production-only approximations (ADR 0014):

* stored baselines keep only (lang, title, hour) slots with a non-zero median, i.e. present on
  at least half of their observation days (a slot present less often has median = MAD = 0,
  exactly). A title with no stored slot is treated as unseen (language prior, no R1), which is
  more conservative than the batch rule for rarely-present titles;
* automation flags use the hours of the current day available so far.
"""

from __future__ import annotations

from datetime import date, timedelta

from lookedup.analytics.config import AnalyticsConfig
from lookedup.analytics.scoring import observation_counts, prior_sql


def daily_baselines_sql(src: str, day: date, cfg: AnalyticsConfig, restrict: str | None = None,
                        bucket: tuple[int, int] | None = None, include_prior: bool = True) -> str:
    """Baseline slots for every (lang, title, hour_of_day) with a non-zero median on ``day``'s day type.

    Plus one row per language with ``title IS NULL`` carrying the language prior. ``restrict``
    (a relation of lang, title) limits the slots to those titles; each title's slots depend only
    on its own history, so the result for those titles is unchanged (used for spot checks).
    ``bucket=(i, n)`` keeps titles with hash(lang, title) % n = i, so callers can build the slots
    in n smaller passes with bounded memory and spill (ADR 0018).
    """
    b = cfg.baseline
    n = observation_counts(day, cfg)
    weekend = day.weekday() in b["weekend_days"]
    n_dt = n["weekend"] if weekend else n["weekday"]
    use_dt = n_dt >= b["min_observations"]
    n_use = n_dt if use_dt else n["all"]
    level = "day_type" if use_dt else "hour"
    lo = max(day - timedelta(days=b["lookback_days"]), cfg.period_start)
    dt_filter = f"AND is_weekend = {str(weekend).lower()}" if use_dt else ""
    return f"""
        WITH lb AS (
            SELECT lang, title, hour_of_day, views FROM {src}
            WHERE day >= DATE '{lo}' AND day < DATE '{day}' {dt_filter}
            {f"AND (lang, title) IN (SELECT lang, title FROM {restrict})" if restrict else ""}
            {f"AND hash(lang || '|' || title) % {bucket[1]} = {bucket[0]}" if bucket else ""}
        ), present AS (
            SELECT lang, title, hour_of_day FROM lb GROUP BY ALL HAVING 2 * count(*) >= {n_use}
        ), slots AS (
            SELECT lb.lang, lb.title, lb.hour_of_day, list(lb.views) AS vals
            FROM lb SEMI JOIN present p ON p.lang = lb.lang AND p.title = lb.title AND p.hour_of_day = lb.hour_of_day
            GROUP BY ALL
        ), stats AS (
            SELECT lang, title, hour_of_day,
                   list_aggregate(list_resize(vals, {n_use}, 0), 'median')::DOUBLE AS baseline_median,
                   list_aggregate(list_resize(vals, {n_use}, 0), 'mad')::DOUBLE AS baseline_mad
            FROM slots
        )
        SELECT DATE '{day}' AS day, lang, title, hour_of_day, baseline_median, baseline_mad,
               '{level}' AS baseline_level, {n_use} AS n_obs
        FROM stats WHERE baseline_median > 0 OR baseline_mad > 0
        {f"""UNION ALL
        SELECT DATE '{day}' AS day, lang, NULL AS title, NULL AS hour_of_day, prior_median, prior_mad,
               'prior' AS baseline_level, NULL AS n_obs
        FROM ({prior_sql(src, day, cfg)})""" if include_prior else ""}
    """


def score_hour_sql(src: str, baselines: str, day: date, hour: int, cfg: AnalyticsConfig) -> str:
    """Candidates of one hour scored against stored baselines, with R1/R2 and partial-day automation flags.

    ``src`` must contain the rows of ``day`` (up to ``hour``) and of the previous day.
    """
    s, a = cfg.spike, cfg.automation
    ts = f"TIMESTAMP '{day} {hour:02d}:00:00'"
    return f"""
        WITH cand AS MATERIALIZED (
            SELECT * FROM {src} WHERE ts_hour_start = {ts} AND views >= {s.min_views}
        ), near AS MATERIALIZED (
            -- the candidates' own rows of the previous 24 h: one small table for every lag
            SELECT ts_hour_start, lang, title, views FROM {src}
            WHERE ts_hour_start >= {ts} - INTERVAL 24 HOUR AND ts_hour_start < {ts}
              AND (lang, title) IN (SELECT lang, title FROM cand)
        ), known AS (
            SELECT DISTINCT lang, title FROM {baselines} WHERE title IS NOT NULL
        ), b AS (
            SELECT c.*, k.lang IS NULL AS unseen, sl.baseline_median AS slot_median, sl.baseline_mad AS slot_mad,
                   sl.baseline_level AS slot_level, pr.baseline_median AS prior_median, pr.baseline_mad AS prior_mad
            FROM cand c
            LEFT JOIN known k ON k.lang = c.lang AND k.title = c.title
            LEFT JOIN {baselines} sl ON sl.lang = c.lang AND sl.title = c.title AND sl.hour_of_day = c.hour_of_day
            LEFT JOIN {baselines} pr ON pr.lang = c.lang AND pr.title IS NULL
        ), probes AS (
            SELECT c.lang, c.title, o.k, c.ts_hour_start - to_hours(o.k) AS ts_probe
            FROM cand c CROSS JOIN (VALUES (24), (1), (2), (3)) o(k)
        ), lags AS (
            SELECT p.lang, p.title,
                   coalesce(max(n.views) FILTER (WHERE p.k = 24), 0) AS views_yesterday,
                   coalesce(max(n.views) FILTER (WHERE p.k = 1), 0) AS v_m1,
                   coalesce(max(n.views) FILTER (WHERE p.k = 2), 0) AS v_m2,
                   coalesce(max(n.views) FILTER (WHERE p.k = 3), 0) AS v_m3
            FROM probes p LEFT JOIN near n ON n.lang = p.lang AND n.title = p.title AND n.ts_hour_start = p.ts_probe
            GROUP BY ALL
        ), lagged AS (
            SELECT b.*,
                   CASE WHEN unseen THEN coalesce(prior_median, 0) ELSE coalesce(slot_median, 0) END AS baseline_median,
                   CASE WHEN unseen THEN coalesce(prior_mad, 0) ELSE coalesce(slot_mad, 0) END AS baseline_mad,
                   CASE WHEN unseen THEN 'prior' ELSE coalesce(slot_level, 'zero') END AS baseline_level,
                   lg.views_yesterday,
                   list_aggregate([lg.v_m1, lg.v_m2, lg.v_m3], 'median')::DOUBLE AS prev3_median
            FROM b JOIN lags lg ON lg.lang = b.lang AND lg.title = b.title
        ), flags AS (
            SELECT lang, title,
                   sum(views) AS day_views_so_far,
                   sum(views_mobile) / sum(views)::DOUBLE AS mobile_share_so_far,
                   count(*) AS hours_so_far,
                   sum(views) / ({hour} + 1.0) AS hourly_mean,
                   sqrt(greatest(sum(views::DOUBLE * views) / ({hour} + 1.0) - (sum(views) / ({hour} + 1.0)) ^ 2, 0))
                       / (sum(views) / ({hour} + 1.0)) AS hourly_cv
            FROM {src} WHERE ts_hour_start::DATE = DATE '{day}' AND ts_hour_start <= {ts}
              AND (lang, title) IN (SELECT lang, title FROM cand)
            GROUP BY ALL
        )
        SELECT l.ts_hour_start, l.lang, l.title, l.views, l.views_desktop, l.views_mobile, l.mobile_share,
               l.baseline_level, l.unseen, l.baseline_median, l.baseline_mad, l.views_yesterday, l.prev3_median,
               (l.views - l.baseline_median) / ({s.mad_scale} * l.baseline_mad + sqrt(l.baseline_median) + 1) AS surprise,
               (NOT l.unseen) AND l.views >= {s.r1_ratio} * l.views_yesterday AS r1,
               l.views >= {s.r2_ratio} * l.prev3_median AS r2,
               (f.day_views_so_far >= {a['day_views_min']} AND f.mobile_share_so_far < {a['mobile_share_max']})
                 OR ({hour} >= 5 AND f.hourly_mean >= {a['flat_hourly_mean_min']} AND f.hourly_cv < {a['flat_cv_max']})
                 AS is_automated
        FROM lagged l LEFT JOIN flags f ON f.lang = l.lang AND f.title = l.title
    """
