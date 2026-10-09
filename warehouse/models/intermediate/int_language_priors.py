"""Language-level prior (median, MAD) per scored day, for unseen entities (prereg §2). Incremental by day."""

from lookedup.analytics.batch import pending_days, run_by_day
from lookedup.analytics.config import load
from lookedup.analytics.scoring import prior_sql


def model(dbt, session):
    dbt.config(materialized="incremental")
    cfg = load()
    dbt.ref("stg_hourly").create_view("_stg_hourly_pr", replace=True)
    days = pending_days(session, dbt.this, dbt.is_incremental, cfg.eval_start, cfg.period_end)
    return run_by_day(session, days, lambda d: f"""
        select date '{d:%Y-%m-%d}' as day, * from ({prior_sql('_stg_hourly_pr', d, cfg)})""",
        "_new_language_priors")
