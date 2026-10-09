"""Every article-hour with >= 100 views in the evaluation period, scored against its baseline.

Baseline = median/MAD of the previous 28 days (same hour of day and day type, absent = 0),
falling back to the same hour of day, then to the language prior for unseen entities.
Carries the R1/R2 inputs and the surprise score (prereg §2). Incremental by day.
"""

from lookedup.analytics.batch import pending_days, run_by_day
from lookedup.analytics.config import load
from lookedup.analytics.scoring import scored_candidates_sql


def model(dbt, session):
    dbt.config(materialized="incremental")
    cfg = load()
    dbt.ref("stg_hourly").create_view("_stg_hourly_bl", replace=True)
    dbt.ref("int_language_priors").create_view("_priors_bl", replace=True)
    days = pending_days(session, dbt.this, dbt.is_incremental, cfg.eval_start, cfg.period_end)

    def sql(d):
        session.execute(f"create or replace temp view _prior_day as select lang, prior_median, prior_mad "
                        f"from _priors_bl where day = date '{d:%Y-%m-%d}'")
        return f"""select lang || '|' || title || '|' || strftime(ts_hour_start, '%Y%m%dT%H') as candidate_id, *
                   from ({scored_candidates_sql('_stg_hourly_bl', d, cfg, '_prior_day')})"""

    return run_by_day(session, days, sql, "_new_baselines")
