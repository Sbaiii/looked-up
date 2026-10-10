"""Forecasting feature table (docs/prereg_phase4.md): one row per multi-language product event and snapshot
offset (t0, t0 + 1 h, t0 + 3 h, t0 = detection hour), with decision-time features and the M1/M2 targets."""

from lookedup.analytics.config import load
from lookedup.forecast.features import snapshot_sql


def model(dbt, session):
    dbt.config(materialized="table")
    cfg = load()
    dbt.ref("fct_app_events").create_view("_snap_events", replace=True)
    dbt.ref("int_spikes").create_view("_snap_int_spikes", replace=True)
    session.execute("""create or replace temp view _snap_spikes as
        select qid, lang, title, ts_hour_start, surprise, views, baseline_median
        from _snap_int_spikes where not is_automated and qid is not null""")
    dbt.ref("int_baselines").create_view("_snap_views", replace=True)
    dbt.ref("dim_entities").create_view("_snap_dims", replace=True)
    data_end = f"{cfg.period_end:%Y-%m-%d} 23:00:00"
    return session.sql(snapshot_sql("_snap_events", "_snap_spikes", "_snap_views", "_snap_dims",
                                    targets=True, data_end=data_end))
