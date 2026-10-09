"""Pre-registered Phase 2 metrics (docs/prereg_phase2.md §4–6).

Everything is computed from the warehouse (int_spikes, dim_entities, fct_attention_events)
and data/eval/current_events.parquet. Event variants for the ablation grid are rebuilt with
the same lookedup.analytics.events implementation as the warehouse and production.
"""

from __future__ import annotations

import itertools
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import duckdb

from lookedup import db
from lookedup.analytics.config import AnalyticsConfig, EventParams
from lookedup.analytics.events import events_sql

log = logging.getLogger(__name__)


@dataclass
class Context:
    con: duckdb.DuckDBPyConnection
    cfg: AnalyticsConfig

    @property
    def eval_start(self) -> date:
        return self.cfg.eval_start

    @property
    def end(self) -> date:
        return self.cfg.period_end


def open_context(warehouse_db, current_events, cfg: AnalyticsConfig) -> Context:
    con = db.connect()
    con.execute(f"ATTACH '{warehouse_db}' AS wh (READ_ONLY)")
    con.execute(f"CREATE VIEW gt AS SELECT * FROM read_parquet('{current_events}')")
    con.execute("CREATE VIEW spikes_ok AS SELECT * FROM wh.main.int_spikes WHERE NOT is_automated")
    # S1 (ADR 0013): automation filter with the flat rule switched off (low-mobile rule only)
    con.execute("CREATE VIEW spikes_s1 AS SELECT * FROM wh.main.int_spikes WHERE NOT is_low_mobile")
    # major (date, qid) pairs in the evaluation period, one row per pair (+ the sections it appears in)
    con.execute(f"""CREATE TABLE majors AS
        SELECT date, qid, list(DISTINCT section ORDER BY section) AS sections, any_value(link_title) AS title
        FROM gt WHERE is_major AND date BETWEEN DATE '{cfg.eval_start}' AND DATE '{cfg.period_end}'
        GROUP BY date, qid""")
    # S2 (ADR 0013): story headers only (depth-1 bullets)
    con.execute(f"""CREATE TABLE majors_s2 AS
        SELECT date, qid, list(DISTINCT section ORDER BY section) AS sections, any_value(link_title) AS title
        FROM gt WHERE is_major AND depth = 1 AND date BETWEEN DATE '{cfg.eval_start}' AND DATE '{cfg.period_end}'
        GROUP BY date, qid""")
    con.execute("CREATE TABLE portal_qids AS SELECT DISTINCT date, qid FROM gt WHERE qid IS NOT NULL")
    return Context(con, cfg)


def variant_events(ctx: Context, p: EventParams, name: str, spikes: str = "spikes_ok") -> str:
    """Materialise the events of one parameter set as table ``name`` (no excess views)."""
    ev, _ = events_sql(spikes, p)
    ctx.con.execute(f"CREATE OR REPLACE TABLE {name} AS {ev}")
    return name


def recall(ctx: Context, events: str, window_h: int, majors: str = "majors") -> dict:
    """Share of major (date, qid) pairs with an event start in [date - w, date + 24h + w)."""
    r = ctx.con.execute(f"""
        WITH hit AS (
            SELECT m.date, m.qid, bool_or(e.qid IS NOT NULL) AS detected
            FROM {majors} m LEFT JOIN {events} e ON e.qid = m.qid
             AND e.start_hour >= m.date::TIMESTAMP - INTERVAL {window_h} HOUR
             AND e.start_hour <  m.date::TIMESTAMP + INTERVAL 24 HOUR + INTERVAL {window_h} HOUR
            GROUP BY ALL
        )
        SELECT count(*), count(*) FILTER (WHERE detected) FROM hit""").fetchone()
    return {"pairs": r[0], "detected": r[1], "recall": r[1] / r[0] if r[0] else None}


def recall_by_section(ctx: Context, events: str, window_h: int) -> list[tuple]:
    return ctx.con.execute(f"""
        WITH hit AS (
            SELECT m.date, m.qid, m.sections, bool_or(e.qid IS NOT NULL) AS detected
            FROM majors m LEFT JOIN {events} e ON e.qid = m.qid
             AND e.start_hour >= m.date::TIMESTAMP - INTERVAL {window_h} HOUR
             AND e.start_hour <  m.date::TIMESTAMP + INTERVAL 24 HOUR + INTERVAL {window_h} HOUR
            GROUP BY ALL
        ), s AS (SELECT unnest(sections) AS section, detected FROM hit)
        SELECT section, count(*) AS pairs, count(*) FILTER (WHERE detected) AS detected,
               round(count(*) FILTER (WHERE detected) / count(*), 3) AS recall
        FROM s GROUP BY 1 ORDER BY pairs DESC""").fetchall()


def precision_proxy(ctx: Context, events: str) -> dict:
    """Share of events (in the evaluation period) whose QID is linked from the portal within ±2 days."""
    k = ctx.cfg.raw["evaluation"]["precision_window_days"]
    r = ctx.con.execute(f"""
        WITH e AS (SELECT * FROM {events} WHERE start_hour::DATE BETWEEN DATE '{ctx.eval_start}' AND DATE '{ctx.end}'),
        m AS (
            SELECT e.qid, e.start_hour, bool_or(p.qid IS NOT NULL) AS in_portal
            FROM e LEFT JOIN portal_qids p ON p.qid = e.qid
             AND p.date BETWEEN e.start_hour::DATE - {k} AND e.start_hour::DATE + {k}
            GROUP BY ALL
        )
        SELECT count(*), count(*) FILTER (WHERE in_portal) FROM m""").fetchone()
    return {"events": r[0], "in_portal": r[1], "precision_proxy": r[1] / r[0] if r[0] else None}


def ablation_grid(ctx: Context) -> list[dict]:
    """All 27 configurations; the winner maximises the harmonic mean of recall_24h and precision proxy."""
    ab = ctx.cfg.raw["ablations"]
    out = []
    for r3, n, w in itertools.product(ab["r3_threshold"], ab["min_languages"], ab["window_hours"]):
        p = ctx.cfg.event_variant(r3_threshold=r3, min_languages=n, window_hours=w)
        t = variant_events(ctx, p, "_variant")
        r6, r24, pp = recall(ctx, t, 6), recall(ctx, t, 24), precision_proxy(ctx, t)
        hm = (2 * r24["recall"] * pp["precision_proxy"] / (r24["recall"] + pp["precision_proxy"])
              if r24["recall"] and pp["precision_proxy"] else 0.0)
        out.append({"r3_threshold": r3, "min_languages": n, "window_hours": w, "events": pp["events"],
                    "recall_6h": r6["recall"], "recall_24h": r24["recall"], "precision_proxy": pp["precision_proxy"],
                    "harmonic_mean": hm,
                    "primary": (r3, n, w) == (ctx.cfg.spike.r3_threshold, ctx.cfg.event.min_languages,
                                              ctx.cfg.event.window_hours)})
        log.info("ablation r3=%s n=%s w=%s: events=%s r6=%.3f r24=%.3f p=%.3f", r3, n, w, pp["events"],
                 r6["recall"], r24["recall"], pp["precision_proxy"])
    best = max(out, key=lambda x: x["harmonic_mean"])
    for row in out:
        row["winner"] = row is best
    return out


def lead_counts(ctx: Context, events: str) -> list[tuple]:
    return ctx.con.execute(f"""SELECT lead_lang, count(*) FROM {events}
        WHERE start_hour::DATE BETWEEN DATE '{ctx.eval_start}' AND DATE '{ctx.end}'
        GROUP BY 1 ORDER BY 2 DESC""").fetchall()


def h4_spread(ctx: Context, events: str) -> dict:
    """Median spread lag, deaths+disasters vs sports+entertainment, one-sided Mann-Whitney U."""
    from scipy.stats import mannwhitneyu

    ev = ctx.cfg.raw["evaluation"]
    rows = ctx.con.execute(f"""SELECT category, median_spread_lag_hours FROM {events}
        WHERE start_hour::DATE BETWEEN DATE '{ctx.eval_start}' AND DATE '{ctx.end}'
          AND median_spread_lag_hours IS NOT NULL""").fetchall()
    a = [lag for c, lag in rows if c in ("death", "disaster")]
    b = [lag for c, lag in rows if c in ("sports", "entertainment")]
    res = {"n_a": len(a), "n_b": len(b)}
    if len(a) < ev["h4_min_group_size"] or len(b) < ev["h4_min_group_size"]:
        return {**res, "verdict": "inconclusive (group < 10)"}
    import statistics

    u = mannwhitneyu(a, b, alternative="less")
    ma, mb = statistics.median(a), statistics.median(b)
    supported = u.pvalue < ev["h4_alpha"] and ma < mb
    return {**res, "median_a": ma, "median_b": mb, "U": float(u.statistic), "p_value": float(u.pvalue),
            "verdict": "supported" if supported else "rejected"}


def matched_events(ctx: Context, events: str, window_h: int = 24) -> str:
    """Events matched to a major portal pair (same QID, within the recall window) -> table name."""
    ctx.con.execute(f"""CREATE OR REPLACE TABLE matched AS
        SELECT DISTINCT e.*, m.date AS portal_date
        FROM {events} e JOIN majors m ON e.qid = m.qid
         AND e.start_hour >= m.date::TIMESTAMP - INTERVAL {window_h} HOUR
         AND e.start_hour <  m.date::TIMESTAMP + INTERVAL 24 HOUR + INTERVAL {window_h} HOUR""")
    return "matched"


def h2_lead_language(ctx: Context, events: str, claims_cache) -> dict:
    """Lead language vs official languages of the event's country (P17, else P276 -> P17)."""
    from lookedup.analytics.entities import fetch_claims

    matched_events(ctx, events)
    rows = ctx.con.execute("""SELECT m.event_id, m.qid, m.lead_lang, d.countries, d.locations
        FROM matched m LEFT JOIN wh.main.dim_entities d USING (qid)""").fetchall()
    official = {int(k[1:]): v for k, v in ctx.cfg.raw["official_languages"].items()}
    locs = {q for r in rows if not r[3] for q in (r[4] or [])}
    loc_claims = _claims(fetch_claims(locs, claims_cache)) if locs else {}
    events_country = {}
    for event_id, qid, lead, countries, locations in rows:
        cs = list(countries or [])
        if not cs:
            for l in locations or []:
                cs += loc_claims.get(l, {}).get("P17", [])
        events_country[event_id] = (lead, sorted(set(cs)))
    country_ids = {c for _, cs in events_country.values() for c in cs}
    c_claims = _claims(fetch_claims(country_ids, claims_cache)) if country_ids else {}
    langs_of = {c: {official[l] for l in c_claims.get(c, {}).get("P37", []) if l in official} for c in country_ids}
    geo, hits, geo_non_en, hits_non_en = 0, 0, 0, 0
    for lead, cs in events_country.values():
        langs = set().union(*(langs_of.get(c, set()) for c in cs)) if cs else set()
        if not langs:
            continue
        geo += 1
        hits += lead in langs
        if "en" not in langs:
            geo_non_en += 1
            hits_non_en += lead in langs
    base = ctx.con.execute(f"""SELECT avg((lead_lang = 'en')::INT) FROM {events}
        WHERE start_hour::DATE BETWEEN DATE '{ctx.eval_start}' AND DATE '{ctx.end}'""").fetchone()[0]
    share = hits / geo if geo else None
    return {"matched_events": len(rows), "geolocatable": geo, "lead_is_official": hits, "share": share,
            "geolocatable_non_english_countries": geo_non_en, "share_non_english_countries":
            hits_non_en / geo_non_en if geo_non_en else None, "base_rate_lead_en": base,
            "verdict": None if share is None else ("supported" if share >= 0.60 else "rejected")}


def _claims(table) -> dict[int, dict]:
    return {q: json.loads(c) for q, c in zip(table["qid"].to_pylist(), table["claims_json"].to_pylist())}


def detection_delays(ctx: Context, events: str) -> dict:
    """start_hour - known event time for detected major pairs (infobox timestamp, else new-article creation)."""
    from lookedup.evaluation.timestamps import event_time

    matched_events(ctx, events, window_h=24)
    rows = ctx.con.execute("""SELECT DISTINCT m.portal_date, m.qid, m.start_hour, mj.title
        FROM matched m JOIN majors mj ON mj.qid = m.qid AND mj.date = m.portal_date""").fetchall()
    delays = []
    for portal_date, qid, start, title in rows:
        t = event_time(title, portal_date)
        if t is None:
            continue
        delays.append({"qid": qid, "title": title, "portal_date": portal_date, "event_time": t["time"],
                       "source": t["source"], "start_hour": start,
                       "delay_hours": (start - t["time"].replace(minute=0, second=0)).total_seconds() / 3600})
    vals = sorted(d["delay_hours"] for d in delays)
    if not vals:
        return {"n": 0, "rows": []}

    def q(p):
        return vals[min(len(vals) - 1, int(p * (len(vals) - 1)))]
    return {"n": len(vals), "median": q(0.5), "p25": q(0.25), "p75": q(0.75),
            "share_le_6h": sum(0 <= v <= 6 for v in vals) / len(vals),
            "share_negative": sum(v < 0 for v in vals) / len(vals), "rows": delays}


def event_count(ctx: Context, events: str) -> int:
    return ctx.con.execute(f"""SELECT count(*) FROM {events}
        WHERE start_hour::DATE BETWEEN DATE '{ctx.eval_start}' AND DATE '{ctx.end}'""").fetchone()[0]


def to_jsonable(x):
    if isinstance(x, (datetime, date)):
        return x.isoformat()
    if isinstance(x, timedelta):
        return x.total_seconds()
    raise TypeError(type(x))
