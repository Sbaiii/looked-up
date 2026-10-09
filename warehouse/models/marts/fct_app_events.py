"""Attention events under the PRODUCT configuration (ADR 0021: >= 2 languages, tiers), one row per event."""

from lookedup.analytics.batch import prepare_event_inputs
from lookedup.analytics.config import load
from lookedup.analytics.events import build_events


def model(dbt, session):
    dbt.config(materialized="table")
    cfg = load()
    spikes, scored = prepare_event_inputs(session, dbt.ref("int_spikes"), dbt.ref("int_baselines"), "ap")
    events, _ = build_events(session, spikes, cfg.product_event, scored=scored)
    events.create_view("_events_ap", replace=True)
    dbt.ref("dim_entities").create_view("_dim_ap", replace=True)
    ev = cfg.raw["evaluation"]
    return session.sql(f"""
        select e.*, d.label_en, d.entity_class, d.is_human,
               case when d.is_human and len(list_filter(d.dates_of_death, x -> try_cast(x as date) is not null
                        and date_diff('day', try_cast(x as date), cast(e.start_hour as date))
                            between -{ev['death_window_days_after']} and {ev['death_window_days_before']})) > 0
                    then 'death' else coalesce(d.entity_class, 'other') end as category
        from _events_ap e left join _dim_ap d using (qid)
    """)
