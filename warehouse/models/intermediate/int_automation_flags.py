"""(lang, title, day) with day views >= 500 and the two automation flags (prereg §2). Incremental by day."""

from lookedup.analytics.batch import pending_days, run_by_day
from lookedup.analytics.config import load
from lookedup.analytics.scoring import automation_flags_sql


def model(dbt, session):
    dbt.config(materialized="incremental")
    cfg = load()
    dbt.ref("stg_hourly").create_view("_stg_hourly_af", replace=True)
    days = pending_days(session, dbt.this, dbt.is_incremental, cfg.period_start, cfg.period_end)
    return run_by_day(session, days, lambda d: f"""
        select lang || '|' || title || '|' || strftime(day, '%Y-%m-%d') as flag_id, *
        from ({automation_flags_sql('_stg_hourly_af', d, cfg)})""", "_new_automation_flags")
