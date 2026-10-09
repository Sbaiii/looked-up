"""Wikidata claims for event entities (P31, P106, P570, P17, P276, P37) and coarse classes.

Claims are fetched with ``wbgetentities`` (50 ids per call) and cached in a Parquet file,
so re-runs only fetch new QIDs. Classes follow the priority order of ``categories`` in
config/analytics.yml (prereg §2); ``death`` is decided per event (it needs the event date).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import requests

from lookedup.analytics.config import AnalyticsConfig
from lookedup.dumps import session

log = logging.getLogger(__name__)

API = "https://www.wikidata.org/w/api.php"
PROPS = ("P31", "P106", "P570", "P17", "P276", "P37")
SCHEMA = pa.schema([("qid", pa.int64()), ("label_en", pa.string()), ("claims_json", pa.string())])


def _item_ids(claims: dict, prop: str) -> list[int]:
    out = []
    for c in claims.get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and "numeric-id" in v:
            out.append(int(v["numeric-id"]))
    return out


def _dates(claims: dict, prop: str) -> list[str]:
    out = []
    for c in claims.get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and "time" in v:
            out.append(v["time"])  # e.g. "+2026-08-28T00:00:00Z"
    return out


def parse_entity(e: dict) -> dict:
    """Keep only the properties we use: {prop: [numeric ids]} and P570 as ISO dates."""
    claims = e.get("claims", {})
    out = {p: _item_ids(claims, p) for p in PROPS if p != "P570"}
    out["P570"] = [t.lstrip("+")[:10] for t in _dates(claims, "P570")]
    return out


SPARQL = "https://query.wikidata.org/sparql"


def _sparql(query: str) -> list[dict]:
    for attempt in range(5):
        try:
            r = session().post(SPARQL, data={"query": query}, timeout=120,
                               headers={"Accept": "application/sparql-results+json"})
            r.raise_for_status()
            return r.json()["results"]["bindings"]
        except (requests.RequestException, ValueError) as e:
            if attempt == 4:
                raise
            log.warning("sparql failed (%s), retry %d", e, attempt + 1)
            time.sleep(5 * (attempt + 1))
    return []


def fetch_claims_sparql(qids: list[int], batch: int = 500) -> list[dict]:
    """Same output as the wbgetentities path, via the Wikidata Query Service (much lighter)."""
    rows = []
    for i in range(0, len(qids), batch):
        chunk = qids[i:i + batch]
        values = " ".join(f"wd:Q{q}" for q in chunk)
        claims: dict[int, dict] = {q: {p: [] for p in PROPS} for q in chunk}
        props = " ".join(f"wdt:{p}" for p in PROPS)
        for b in _sparql(f"SELECT ?item ?p ?v WHERE {{ VALUES ?item {{ {values} }} VALUES ?p {{ {props} }} ?item ?p ?v . }}"):
            q = int(b["item"]["value"].rsplit("/Q", 1)[1])
            prop = b["p"]["value"].rsplit("/", 1)[1]
            v = b["v"]["value"]
            if prop == "P570":
                claims[q]["P570"].append(v[:10])
            elif "/entity/Q" in v:
                claims[q][prop].append(int(v.rsplit("/Q", 1)[1]))
        labels = {int(b["item"]["value"].rsplit("/Q", 1)[1]): b["l"]["value"] for b in _sparql(
            f"SELECT ?item ?l WHERE {{ VALUES ?item {{ {values} }} ?item rdfs:label ?l . FILTER(lang(?l) = 'en') }}")}
        for q in chunk:
            rows.append({"qid": q, "label_en": labels.get(q), "claims_json": json.dumps(claims[q])})
        log.info("claims (sparql): %d/%d fetched", min(i + batch, len(qids)), len(qids))
        time.sleep(1)
    return rows


def fetch_claims(qids: Iterable[int], cache: Path, batch: int = 50) -> pa.Table:
    """Claims for ``qids``, fetching only those missing from the Parquet ``cache``.

    Uses the Query Service in batches of 500; falls back to wbgetentities if it fails.
    """
    have = pq.read_table(cache) if cache.exists() else SCHEMA.empty_table()
    known = set(have["qid"].to_pylist())
    todo = sorted(set(int(q) for q in qids) - known)
    try:
        rows = fetch_claims_sparql(todo)
        todo = []
    except requests.RequestException as e:
        log.warning("query service unavailable (%s), using wbgetentities", e)
        rows = []
    for i in range(0, len(todo), batch):
        ids = "|".join(f"Q{q}" for q in todo[i:i + batch])
        for attempt in range(5):
            try:
                r = session().get(API, params={"action": "wbgetentities", "ids": ids, "props": "claims|labels",
                                               "languages": "en", "format": "json"}, timeout=60)
                r.raise_for_status()
                ents = r.json().get("entities", {})
                break
            except (requests.RequestException, ValueError) as e:
                if attempt == 4:
                    raise
                log.warning("wbgetentities failed (%s), retry %d", e, attempt + 1)
                time.sleep(3 * (attempt + 1))
        for key, e in ents.items():
            if not key.startswith("Q") or "missing" in e:
                continue
            rows.append({"qid": int(key[1:]), "label_en": e.get("labels", {}).get("en", {}).get("value"),
                         "claims_json": json.dumps(parse_entity(e))})
        if (i // batch) % 20 == 0:
            log.info("claims: %d/%d fetched", min(i + batch, len(todo)), len(todo))
        time.sleep(0.2)
    table = pa.concat_tables([have, pa.Table.from_pylist(rows, schema=SCHEMA)]) if rows else have
    if rows:
        cache.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, cache)
    return table


def classify(claims: dict, cfg: AnalyticsConfig) -> str:
    """Coarse class from P31 (priority order of the config), P106 for humans; 'human' / 'other' otherwise."""
    p31 = {f"Q{q}" for q in claims.get("P31", [])}
    if cfg.raw["human_class"] in p31:
        p106 = {f"Q{q}" for q in claims.get("P106", [])}
        for cls, occ in cfg.raw["occupations"].items():
            if p106 & set(occ):
                return cls
        return "human"
    for cls, members in cfg.raw["categories"].items():
        if p31 & set(members):
            return cls
    return "other"


def is_generic(claims: dict, cfg: AnalyticsConfig) -> bool:
    return bool({f"Q{q}" for q in claims.get("P31", [])} & set(cfg.raw["generic_classes"]))


def died_near(claims: dict, start: date, cfg: AnalyticsConfig) -> bool:
    """True if a P570 date falls in [start - 7 days, start + 1 day] (prereg §2, Category)."""
    ev = cfg.raw["evaluation"]
    for d in claims.get("P570", []):
        try:
            died = date.fromisoformat(d)
        except ValueError:
            continue
        if -ev["death_window_days_after"] <= (start - died).days <= ev["death_window_days_before"]:
            return True
    return False
