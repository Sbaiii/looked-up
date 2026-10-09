"""Entities that can form attention events: labels in the 30 languages, Wikidata class, death dates.

Scope: every QID that forms an event under the LOOSEST ablation settings (lowest R3, fewest
languages, widest window), so that every ablation can be classified. Claims come from the
Wikidata API and are cached in data/warehouse/entity_claims.parquet (only new QIDs are fetched).
"""

import json

import pyarrow as pa

from lookedup.analytics.config import load
from lookedup.analytics.entities import classify, fetch_claims, is_generic
from lookedup.analytics.events import build_events
from lookedup.settings import DATA_DIR


def model(dbt, session):
    dbt.config(materialized="table")
    cfg = load()
    ab = cfg.raw["ablations"]
    dbt.ref("int_spikes").create_view("_spikes_dim", replace=True)
    session.execute("create or replace temp view _spikes_dim_ok as select * from _spikes_dim where not is_automated")
    loose = cfg.event_variant(r3_threshold=min(ab["r3_threshold"]), min_languages=min(ab["min_languages"]),
                              window_hours=max(ab["window_hours"]))
    events, _ = build_events(session, "_spikes_dim_ok", loose)
    qids = [r[0] for r in events.project("qid").distinct().fetchall()]
    claims = fetch_claims(qids, DATA_DIR / "warehouse" / "entity_claims.parquet")
    wanted = set(qids)
    rows = []
    for qid, label, cj in zip(claims["qid"].to_pylist(), claims["label_en"].to_pylist(),
                              claims["claims_json"].to_pylist()):
        if qid not in wanted:
            continue
        c = json.loads(cj)
        rows.append({"qid": qid, "label_en": label, "entity_class": classify(c, cfg),
                     "is_human": int(cfg.raw["human_class"][1:]) in c.get("P31", []),
                     "is_generic": is_generic(c, cfg), "p31": c.get("P31", []), "dates_of_death": c.get("P570", []),
                     "countries": c.get("P17", []), "locations": c.get("P276", [])})
    schema = pa.schema([("qid", pa.int64()), ("label_en", pa.string()), ("entity_class", pa.string()),
                        ("is_human", pa.bool_()), ("is_generic", pa.bool_()), ("p31", pa.list_(pa.int64())),
                        ("dates_of_death", pa.list_(pa.string())), ("countries", pa.list_(pa.int64())),
                        ("locations", pa.list_(pa.int64()))])
    ents = session.from_arrow(pa.Table.from_pylist(rows, schema=schema))
    ents.create_view("_ents", replace=True)
    dbt.ref("stg_sitelinks").create_view("_sitelinks_dim", replace=True)
    return session.sql("""
        with labels as (
            select s.qid, map_from_entries(list({'k': s.lang, 'v': replace(s.title, '_', ' ')} order by s.lang)) as labels,
                   count(*) as n_languages
            from _sitelinks_dim s semi join _ents e on e.qid = s.qid
            group by s.qid
        )
        select e.*, l.labels, coalesce(l.n_languages, 0) as n_languages
        from _ents e left join labels l using (qid)
    """)
