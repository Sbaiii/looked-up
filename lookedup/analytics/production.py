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


def daily_baselines_sql(src: str, day: date, cfg: AnalyticsConfig) -> str:
    """Baseline slots for every (lang, title, hour_of_day) with a non-zero median on ``day``'s day type.

    Plus one row per language with ``title IS NULL`` carrying the language prior.
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
        UNION ALL
        SELECT DATE '{day}' AS day, lang, NULL AS title, NULL AS hour_of_day, prior_median, prior_mad,
               'prior' AS baseline_level, NULL AS n_obs
        FROM ({prior_sql(src, day, cfg)})
    """


def score_hour_sql(src: str, baselines: str, day: date, hour: int, cfg: AnalyticsConfig) -> str:
    """Candidates of one hour scored against stored baselines, with R1/R2 and partial-day automation flags.

    ``src`` must contain the rows of ``day`` (up to ``hour``) and of the previous day.
    """
    s, a = cfg.spike, cfg.automation
    ts = f"TIMESTAMP '{day} {hour:02d}:00:00'"
    return f"""
        WITH cand AS (
            SELECT * FROM {src} WHERE ts_hour_start = {ts} AND views >= {s.min_views}
        ), known AS (
            SELECT DISTINCT lang, title FROM {baselines} WHERE title IS NOT NULL
        ), b AS (
            SELECT c.*, k.lang IS NULL AS unseen, sl.baseline_median AS slot_median, sl.baseline_mad AS slot_mad,
                   sl.baseline_level AS slot_level, pr.baseline_median AS prior_median, pr.baseline_mad AS prior_mad
            FROM cand c
            LEFT JOIN known k ON k.lang = c.lang AND k.title = c.title
            LEFT JOIN {baselines} sl ON sl.lang = c.lang AND sl.title = c.title AND sl.hour_of_day = c.hour_of_day
            LEFT JOIN {baselines} pr ON pr.lang = c.lang AND pr.title IS NULL
        ), lagged AS (
            SELECT b.*,
                   CASE WHEN unseen THEN coalesce(prior_median, 0) ELSE coalesce(slot_median, 0) END AS baseline_median,
                   CASE WHEN unseen THEN coalesce(prior_mad, 0) ELSE coalesce(slot_mad, 0) END AS baseline_mad,
                   CASE WHEN unseen THEN 'prior' ELSE coalesce(slot_level, 'zero') END AS baseline_level,
                   coalesce(y.views, 0) AS views_yesterday,
                   list_aggregate([coalesce(p1.views, 0), coalesce(p2.views, 0), coalesce(p3.views, 0)], 'median')::DOUBLE
                       AS prev3_median
            FROM b
            LEFT JOIN {src} y  ON y.lang = b.lang AND y.title = b.title AND y.ts_hour_start = b.ts_hour_start - INTERVAL 24 HOUR
            LEFT JOIN {src} p1 ON p1.lang = b.lang AND p1.title = b.title AND p1.ts_hour_start = b.ts_hour_start - INTERVAL 1 HOUR
            LEFT JOIN {src} p2 ON p2.lang = b.lang AND p2.title = b.title AND p2.ts_hour_start = b.ts_hour_start - INTERVAL 2 HOUR
            LEFT JOIN {src} p3 ON p3.lang = b.lang AND p3.title = b.title AND p3.ts_hour_start = b.ts_hour_start - INTERVAL 3 HOUR
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
