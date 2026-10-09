"""Per-day SQL builders: automation flags and scored candidates (baselines + R1/R2/R3).

All builders read a relation named by ``src`` with the columns of ``stg_hourly``:
``ts_hour_start, day, hour_of_day, is_weekend, lang, title, views_desktop, views_mobile,
views, mobile_share``. They return SQL for ONE day, so callers can loop over days
(dbt python models) or score the current day (production).

Pre-registered rules (docs/prereg_phase2.md §2):

* absent (lang, title, hour) rows mean < 5 views and are imputed as 0: medians and MADs are
  taken over lists padded with zeros up to the number of calendar observations;
* baseline = median/MAD of the previous 28 days for the same hour of day and day type
  (weekday/weekend), needing >= 7 observations; else same hour of day (>= 7); entities with no
  row at all in the lookback are "unseen" and use the language-level prior;
* R1 views >= 5 x same hour yesterday; R2 views >= 3 x median(previous 3 hours); both need
  views >= 100; R3 s = (v - med) / (1.4826 MAD + sqrt(med) + 1).
"""

from __future__ import annotations

from datetime import date, timedelta

from lookedup.analytics.config import AnalyticsConfig


def _d(day: date) -> str:
    return f"DATE '{day:%Y-%m-%d}'"


def automation_flags_sql(src: str, day: date, cfg: AnalyticsConfig) -> str:
    """(lang, title, day) rows with day views >= the automation floor, with the two flags."""
    a = cfg.automation
    floor = min(a["day_views_min"], 24 * a["flat_hourly_mean_min"])
    return f"""
        WITH d AS (
            SELECT lang, title, day,
                   sum(views) AS day_views,
                   sum(views_mobile) AS day_views_mobile,
                   sum(views::DOUBLE * views) AS sum_sq
            FROM {src} WHERE day = {_d(day)}
            GROUP BY ALL
            HAVING sum(views) >= {floor}
        ), s AS (
            SELECT *, day_views / 24.0 AS hourly_mean,
                   -- population CV over the 24 hours of the day, absent hours = 0
                   sqrt(greatest(sum_sq / 24.0 - (day_views / 24.0) ^ 2, 0)) / (day_views / 24.0) AS hourly_cv,
                   day_views_mobile / day_views::DOUBLE AS mobile_share
            FROM d
        )
        SELECT lang, title, day, day_views, mobile_share, hourly_mean, hourly_cv,
               day_views >= {a['day_views_min']} AND mobile_share < {a['mobile_share_max']} AS is_low_mobile,
               hourly_mean >= {a['flat_hourly_mean_min']} AND hourly_cv < {a['flat_cv_max']} AS is_flat,
               (day_views >= {a['day_views_min']} AND mobile_share < {a['mobile_share_max']})
                 OR (hourly_mean >= {a['flat_hourly_mean_min']} AND hourly_cv < {a['flat_cv_max']}) AS is_automated
        FROM s
    """


def observation_counts(day: date, cfg: AnalyticsConfig) -> dict[str, int]:
    """Calendar observations in the lookback window [day - 28, day - 1], clipped at period start."""
    b = cfg.baseline
    days = [day - timedelta(days=i) for i in range(1, b["lookback_days"] + 1)]
    days = [d for d in days if d >= cfg.period_start]
    weekend = sum(1 for d in days if d.weekday() in b["weekend_days"])
    return {"all": len(days), "weekend": weekend, "weekday": len(days) - weekend}


def prior_sql(src: str, day: date, cfg: AnalyticsConfig, sample_mod: int = 50) -> str:
    """Language-level prior: median/MAD of hourly views of entities seen on >= 7 days in the lookback.

    Computed on a deterministic 1/``sample_mod`` sample of titles (hash of lang, title) to keep it
    tractable; see ADR 0013. Retained rows only (no zero imputation): the prior describes
    what an hour of an established article looks like.
    """
    b = cfg.baseline
    lo = max(day - timedelta(days=b["lookback_days"]), cfg.period_start)
    return f"""
        WITH h AS (
            SELECT lang, title, day, views FROM {src}
            WHERE day >= {_d(lo)} AND day < {_d(day)} AND hash(lang || title) % {sample_mod} = 0
        ), seen AS (
            SELECT lang, title FROM h GROUP BY ALL HAVING count(DISTINCT day) >= {b['prior_min_days_seen']}
        )
        SELECT h.lang, median(h.views)::DOUBLE AS prior_median, mad(h.views)::DOUBLE AS prior_mad
        FROM h SEMI JOIN seen USING (lang, title)
        GROUP BY h.lang
    """


def scored_candidates_sql(src: str, day: date, cfg: AnalyticsConfig, prior: str,
                          hours: list[int] | None = None) -> str:
    """Every article-hour of ``day`` with views >= min_views, with its baseline and R1/R2/R3 inputs.

    ``prior`` names a relation (lang, prior_median, prior_mad). ``hours`` restricts scoring to
    some hours of the day (production scores one hour at a time).
    """
    b, s = cfg.baseline, cfg.spike
    n = observation_counts(day, cfg)
    lo = max(day - timedelta(days=b["lookback_days"]), cfg.period_start)
    hour_filter = f"AND hour_of_day IN ({', '.join(str(h) for h in hours)})" if hours else ""
    min_obs = b["min_observations"]
    return f"""
        WITH cand AS MATERIALIZED (
            SELECT ts_hour_start, day, hour_of_day, is_weekend, lang, title,
                   views, views_desktop, views_mobile, mobile_share
            FROM {src}
            WHERE day = {_d(day)} AND views >= {s.min_views} {hour_filter}
        ), keys AS (
            SELECT DISTINCT lang, title FROM cand
        ), hist AS MATERIALIZED (
            SELECT h.ts_hour_start, h.day, h.hour_of_day, h.is_weekend, h.lang, h.title, h.views
            FROM {src} h SEMI JOIN keys USING (lang, title)
            WHERE h.day >= {_d(lo - timedelta(days=1))} AND h.day <= {_d(day)}
        ), lookback AS MATERIALIZED (
            SELECT * FROM hist WHERE day >= {_d(lo)} AND day < {_d(day)}
        ), seen AS (
            SELECT DISTINCT lang, title FROM lookback
        ), slot_dt AS (
            SELECT lang, title, hour_of_day, is_weekend, list(views) AS vals FROM lookback GROUP BY ALL
        ), slot_h AS (
            SELECT lang, title, hour_of_day, list(views) AS vals FROM lookback GROUP BY ALL
        ), base AS (
            SELECT c.*,
                   CASE WHEN c.is_weekend THEN {n['weekend']} ELSE {n['weekday']} END AS n_dt,
                   {n['all']} AS n_h,
                   coalesce(dt.vals, []) AS vals_dt,
                   coalesce(sh.vals, []) AS vals_h,
                   (se.lang IS NULL) AS unseen
            FROM cand c
            LEFT JOIN slot_dt dt ON dt.lang = c.lang AND dt.title = c.title
                 AND dt.hour_of_day = c.hour_of_day AND dt.is_weekend = c.is_weekend
            LEFT JOIN slot_h sh ON sh.lang = c.lang AND sh.title = c.title AND sh.hour_of_day = c.hour_of_day
            LEFT JOIN seen se ON se.lang = c.lang AND se.title = c.title
        ), stats AS (
            SELECT b.*,
                   CASE WHEN unseen THEN 'prior'
                        WHEN n_dt >= {min_obs} THEN 'day_type'
                        WHEN n_h >= {min_obs} THEN 'hour'
                        ELSE 'prior' END AS baseline_level,
                   CASE WHEN n_dt >= {min_obs} THEN list_resize(vals_dt, n_dt, 0)
                        ELSE list_resize(vals_h, n_h, 0) END AS padded
            FROM base b
        ), probes AS (
            -- one lookup per (candidate, offset): yesterday's hour and the previous 3 hours, joined once
            SELECT c.lang, c.title, c.ts_hour_start, o.k, c.ts_hour_start - to_hours(o.k) AS ts_probe
            FROM cand c CROSS JOIN (VALUES (24), (1), (2), (3)) o(k)
        ), lags AS (
            SELECT p.lang, p.title, p.ts_hour_start,
                   coalesce(max(h.views) FILTER (WHERE p.k = 24), 0) AS views_yesterday,
                   coalesce(max(h.views) FILTER (WHERE p.k = 1), 0) AS v_m1,
                   coalesce(max(h.views) FILTER (WHERE p.k = 2), 0) AS v_m2,
                   coalesce(max(h.views) FILTER (WHERE p.k = 3), 0) AS v_m3
            FROM probes p LEFT JOIN hist h ON h.lang = p.lang AND h.title = p.title AND h.ts_hour_start = p.ts_probe
            GROUP BY ALL
        ), lagged AS (
            SELECT st.*, lg.views_yesterday, lg.v_m1, lg.v_m2, lg.v_m3
            FROM stats st JOIN lags lg ON lg.lang = st.lang AND lg.title = st.title AND lg.ts_hour_start = st.ts_hour_start
        ), scored AS (
            SELECT l.*,
                   -- a language without a prior (empty sample; never seen on real wikis) falls back to 0
                   CASE WHEN baseline_level = 'prior' THEN coalesce(pr.prior_median, 0)
                        ELSE list_aggregate(padded, 'median')::DOUBLE END AS baseline_median,
                   CASE WHEN baseline_level = 'prior' THEN coalesce(pr.prior_mad, 0)
                        ELSE list_aggregate(padded, 'mad')::DOUBLE END AS baseline_mad,
                   list_aggregate([v_m1, v_m2, v_m3], 'median')::DOUBLE AS prev3_median
            FROM lagged l LEFT JOIN {prior} pr ON pr.lang = l.lang
        )
        SELECT ts_hour_start, day, hour_of_day, is_weekend, lang, title,
               views, views_desktop, views_mobile, mobile_share,
               baseline_level, unseen, baseline_median, baseline_mad,
               views_yesterday, prev3_median,
               (views - baseline_median) / ({s.mad_scale} * baseline_mad + sqrt(baseline_median) + 1) AS surprise,
               (NOT unseen) AND views >= {s.r1_ratio} * views_yesterday AND views >= {s.min_views} AS r1,
               views >= {s.r2_ratio} * prev3_median AND views >= {s.min_views} AS r2
        FROM scored
    """
