"""One row per (attention event, spiking language): first spike, spread lag, peak and excess views."""

from lookedup.analytics.batch import prepare_event_inputs
from lookedup.analytics.config import load
from lookedup.analytics.events import build_events


def model(dbt, session):
    dbt.config(materialized="table")
    cfg = load()
    spikes, scored = prepare_event_inputs(dbt, session, "el")
    _, langs = build_events(session, spikes, cfg.event, scored=scored)
    langs.create_view("_langs_el", replace=True)
    dbt.ref("stg_sitelinks").create_view("_sitelinks_el", replace=True)
    return session.sql("""
        select l.event_id || '|' || l.lang as event_lang_id, l.*, s.title
        from _langs_el l left join _sitelinks_el s on s.qid = l.qid and s.lang = l.lang
    """)
