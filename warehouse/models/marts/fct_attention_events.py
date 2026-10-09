"""Attention events under the PRIMARY configuration (prereg §2), one row per event, with category."""

from lookedup.analytics.batch import prepare_event_inputs
from lookedup.analytics.config import load
from lookedup.analytics.events import build_events


def model(dbt, session):
    dbt.config(materialized="table")
    cfg = load()
    spikes, scored = prepare_event_inputs(session, dbt.ref("int_spikes"), dbt.ref("int_baselines"), "ev")
    events, _ = build_events(session, spikes, cfg.event, scored=scored)
    events.create_view("_events_ev", replace=True)
    dbt.ref("dim_entities").create_view("_dim_ev", replace=True)
    ev = cfg.raw["evaluation"]
    return session.sql(f"""
        select e.*, d.label_en, d.entity_class, d.is_human,
               case when d.is_human and len(list_filter(d.dates_of_death, x -> try_cast(x as date) is not null
                        and date_diff('day', try_cast(x as date), cast(e.start_hour as date))
                            between -{ev['death_window_days_after']} and {ev['death_window_days_before']})) > 0
                    then 'death' else coalesce(d.entity_class, 'other') end as category
        from _events_ev e left join _dim_ev d using (qid)
    """)
