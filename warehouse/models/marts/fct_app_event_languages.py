"""One row per (product event, spiking language): first spike, spread lag, peak and excess views (ADR 0021)."""

from lookedup.analytics.batch import prepare_event_inputs
from lookedup.analytics.config import load
from lookedup.analytics.events import build_events


def model(dbt, session):
    dbt.config(materialized="table")
    cfg = load()
    spikes, scored = prepare_event_inputs(session, dbt.ref("int_spikes"), dbt.ref("int_baselines"), "al")
    _, langs = build_events(session, spikes, cfg.product_event, scored=scored)
    langs.create_view("_langs_al", replace=True)
    dbt.ref("stg_sitelinks").create_view("_sitelinks_al", replace=True)
    return session.sql("""
        select l.event_id || '|' || l.lang as event_lang_id, l.*, s.title
        from _langs_al l left join _sitelinks_al s on s.qid = l.qid and s.lang = l.lang
    """)
