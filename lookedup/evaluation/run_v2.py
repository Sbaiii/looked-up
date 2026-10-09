"""Phase 2b evaluation (docs/prereg_phase2b.md): GT1 deaths, GT2 earthquakes, GT3 matches.

    python -m lookedup.cli evaluate-v2            # build ground truths (cached) and compute all metrics
    python -m lookedup.cli evaluate-v2 --refresh  # refetch the ground truths
"""

from __future__ import annotations

import csv
import json
import logging
import statistics
from datetime import date, datetime, timedelta

from lookedup import db
from lookedup.analytics.config import load
from lookedup.analytics.entities import fetch_claims
from lookedup.analytics.events import events_sql
from lookedup.evaluation import ground_truth_v2 as gt
from lookedup.languages import active_codes
from lookedup.settings import DATA_DIR, ROOT
from lookedup.warehouse import WAREHOUSE_DB

log = logging.getLogger(__name__)

OUT = ROOT / "docs" / "analysis"
CACHE = DATA_DIR / "eval"
CLAIMS = DATA_DIR / "warehouse" / "entity_claims.parquet"
COUNTRY_CLASSES = {6256, 3624078}


def _cached(name: str, build, refresh: bool):
    path = CACHE / f"gt2b_{name}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    rows = json.loads(gt.dump(build()))
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    return rows


def _ts(x) -> datetime | None:
    return datetime.fromisoformat(x) if x else None


def _floor(t: datetime) -> datetime:
    return t.replace(minute=0, second=0, microsecond=0)


class Events:
    """Event lookups (by QID and time window) for the primary table and for ablation variants."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.con = db.connect()
        self.con.execute(f"ATTACH '{WAREHOUSE_DB}' AS wh (READ_ONLY)")
        self.con.execute("CREATE VIEW spikes_ok AS SELECT * FROM wh.main.int_spikes WHERE NOT is_automated")
        self.tables = {"primary": "wh.main.fct_attention_events"}

    def variant(self, min_languages: int) -> str:
        name = f"ev_n{min_languages}"
        if name not in self.tables:
            p = self.cfg.event_variant(min_languages=min_languages)
            ev, _ = events_sql("spikes_ok", p)
            self.con.execute(f"CREATE TABLE {name} AS {ev}")
            self.tables[name] = name
        return self.tables[name]

    def first(self, table: str, qids: list[int], lo: datetime, hi: datetime) -> dict | None:
        """Earliest event for any of ``qids`` with start_hour in [lo, hi]."""
        if not qids:
            return None
        cols = "qid, start_hour, lead_lang, breadth, event_class"
        r = self.con.execute(f"""SELECT {cols} FROM {table} WHERE qid IN (SELECT unnest(?::BIGINT[]))
            AND start_hour BETWEEN ? AND ? ORDER BY start_hour LIMIT 1""", [qids, lo, hi]).fetchone()
        return dict(zip(["qid", "start_hour", "lead_lang", "breadth", "event_class"], r)) if r else None


def _recall(rows: list[dict], key: str = "detected") -> dict:
    n = len(rows)
    d = sum(1 for r in rows if r[key])
    return {"n": n, "detected": d, "recall": d / n if n else None}


def _write(name: str, rows: list[dict]) -> None:
    if not rows:
        return
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def evaluate(refresh: bool = False) -> dict:
    cfg = load()
    langs = active_codes()
    lo_period = datetime.combine(cfg.eval_start, datetime.min.time())
    hi_period = datetime.combine(cfg.period_end + timedelta(days=1), datetime.min.time())  # exclusive
    ev = Events(cfg)
    n_lang = dict(ev.con.execute("SELECT qid, count(DISTINCT lang) FROM wh.main.stg_sitelinks GROUP BY qid").fetchall())
    res: dict = {"config": {"r3": cfg.spike.r3_threshold, "min_languages": cfg.event.min_languages,
                            "window_hours": cfg.event.window_hours}}

    # ---------------- GT1 deaths
    deaths = _cached("deaths", lambda: gt.deaths([(2026, 7), (2026, 8), (2026, 9)], n_lang, 5), refresh)
    gt1, out_of_window = [], 0
    for r in deaths:
        d = date.fromisoformat(r["date"])
        lo = datetime.combine(d, datetime.min.time()) - timedelta(hours=12)
        hi = datetime.combine(d + timedelta(days=1), datetime.min.time()) + timedelta(hours=24)
        if lo < lo_period or hi > hi_period:
            out_of_window += 1
            continue
        hit = ev.first(ev.tables["primary"], [r["qid"]], lo, hi - timedelta(hours=1))
        ann = _ts(r.get("announcement"))
        row = {"date": r["date"], "title": r["title"], "qid": r["qid"], "n_languages": r["n_languages"],
               "detected": hit is not None, "start_hour": hit["start_hour"] if hit else None,
               "lead_lang": hit["lead_lang"] if hit else None, "breadth": hit["breadth"] if hit else None,
               "event_class": hit["event_class"] if hit else None, "announcement": ann,
               "delay_from_announcement_h": ((hit["start_hour"] - _floor(ann)).total_seconds() / 3600)
               if hit and ann else None}
        for n in (2, 5):
            row[f"detected_n{n}"] = ev.first(ev.variant(n), [r["qid"]], lo, hi - timedelta(hours=1)) is not None
        gt1.append(row)
    rec = _recall(gt1)
    res["gt1"] = {"entries_total": len(deaths), "out_of_window": out_of_window, **rec,
                  "verdict_h1b_1": "supported" if rec["recall"] and rec["recall"] >= 0.60 else "rejected",
                  "by_languages": {b: _recall([r for r in gt1 if lo_ <= r["n_languages"] <= hi_])
                                   for b, (lo_, hi_) in {"5-9": (5, 9), "10-19": (10, 19), ">=20": (20, 99)}.items()},
                  "ablation": {f"n{n}": _recall(gt1, f"detected_n{n}") for n in (2, 5)} | {"n3": rec},
                  "by_class": {c: sum(1 for r in gt1 if r["event_class"] == c) for c in ("multi_language", "single_language")}}
    delays = sorted(r["delay_from_announcement_h"] for r in gt1 if r["delay_from_announcement_h"] is not None)
    res["gt1"]["delay_from_announcement"] = _dist(delays)
    _write("phase2b_gt1_deaths.csv", gt1)

    # ---------------- GT2 earthquakes
    q_end = datetime.combine(cfg.period_end, datetime.min.time()) + timedelta(hours=18)
    quakes = _cached("quakes", lambda: gt.quakes(lo_period, q_end, langs), refresh)
    region_qids = {q for r in quakes for q in r["place_qids"]}
    claims = _claims(fetch_claims(region_qids | {c for r in quakes for c in r["article_countries"]}, CLAIMS))
    countries = set()
    for r in quakes:
        r["country"] = _country(r, claims)
        if r["country"]:
            countries.add(r["country"])
    claims |= _claims(fetch_claims(countries, CLAIMS))
    official = {int(k[1:]): v for k, v in cfg.raw["official_languages"].items()}
    gt2 = []
    for r in quakes:
        o = _ts(r["origin"])
        f0 = _floor(o)
        targets = ([r["article_qid"]] if r["article_qid"] else []) + r["place_qids"]
        hit6 = ev.first(ev.tables["primary"], targets, f0, f0 + timedelta(hours=6))
        hit6a = ev.first(ev.tables["primary"], [r["article_qid"]] if r["article_qid"] else [], f0, f0 + timedelta(hours=6))
        hit24 = ev.first(ev.tables["primary"], targets, f0, f0 + timedelta(hours=24))
        c_langs = {official[l] for l in claims.get(r["country"], {}).get("P37", []) if l in official} if r["country"] else set()
        row = {"usgs_id": r["usgs_id"], "origin": o, "mag": r["mag"], "place": r["place"],
               "article_qid": r["article_qid"], "place_qids": " ".join(str(q) for q in r["place_qids"]),
               "country": r["country"], "country_languages": " ".join(sorted(c_langs)),
               "detected": hit6 is not None, "detected_article_only": hit6a is not None,
               "detected_24h": hit24 is not None,
               "start_hour": hit24["start_hour"] if hit24 else None, "lead_lang": hit24["lead_lang"] if hit24 else None,
               "breadth": hit24["breadth"] if hit24 else None, "event_class": hit24["event_class"] if hit24 else None,
               "delay_h": ((hit24["start_hour"] - f0).total_seconds() / 3600) if hit24 else None,
               "lead_is_country_language": (hit24["lead_lang"] in c_langs) if hit24 and c_langs else None}
        for n in (2, 5):
            row[f"detected_n{n}"] = ev.first(ev.variant(n), targets, f0, f0 + timedelta(hours=6)) is not None
        gt2.append(row)
    big = [r for r in gt2 if r["mag"] >= 6.5]
    small = [r for r in gt2 if r["mag"] < 6.5]
    rec_big = _recall(big)
    d24 = sorted(r["delay_h"] for r in gt2 if r["delay_h"] is not None)
    h2b = [r for r in gt2 if r["lead_is_country_language"] is not None]
    share = sum(r["lead_is_country_language"] for r in h2b) / len(h2b) if h2b else None
    res["gt2"] = {
        "quakes": len(gt2), "m65_plus": rec_big, "m60_65": _recall(small),
        "m65_plus_article_only": _recall(big, "detected_article_only"),
        "with_article": sum(1 for r in gt2 if r["article_qid"]),
        "verdict_h1b_2": "supported" if rec_big["recall"] is not None and rec_big["recall"] >= 0.70 else "rejected",
        "ablation_m65": {f"n{n}": _recall(big, f"detected_n{n}") for n in (2, 5)} | {"n3": rec_big},
        "h5_delay": _dist(d24),
        "verdict_h5": ("inconclusive (< 5 detected)" if len(d24) < 5
                       else "supported" if statistics.median(d24) <= 4 else "rejected"),
        "h2b": {"qualifying": len(h2b), "lead_is_country_language": sum(r["lead_is_country_language"] for r in h2b),
                "share": share},
        "verdict_h2b": ("inconclusive (< 5 qualifying)" if len(h2b) < 5
                        else "supported" if share >= 0.60 else "rejected"),
    }
    _write("phase2b_gt2_earthquakes.csv", gt2)

    # ---------------- GT3 matches
    matches = _cached("matches", lambda: gt.matches(["2026 FIFA World Cup knockout stage", "2026 FIFA World Cup final"]),
                      refresh)
    gt3, excluded = [], []
    seen = set()
    for r in matches:
        ko = _ts(r["kickoff"])
        key = (ko, tuple(r["teams"]))
        if key in seen:
            continue
        seen.add(key)
        if ko is None:
            excluded.append({**r, "reason": "no Wikipedia kick-off time"})
            continue
        lo, hi = ko - timedelta(hours=3), ko + timedelta(hours=3)
        if lo < lo_period or hi > hi_period:
            excluded.append({**r, "reason": "out of the scored period"})
            continue
        targets = r["team_qids"] + ([r["match_qid"]] if r.get("match_qid") else [])
        hit = ev.first(ev.tables["primary"], targets, _floor(lo), hi)
        row = {"kickoff": ko, "teams": " vs ".join(r["teams"]), "targets": " ".join(map(str, targets)),
               "detected": hit is not None, "start_hour": hit["start_hour"] if hit else None,
               "lead_lang": hit["lead_lang"] if hit else None, "breadth": hit["breadth"] if hit else None,
               "delay_from_kickoff_h": ((hit["start_hour"] - _floor(ko)).total_seconds() / 3600) if hit else None}
        for n in (2, 5):
            row[f"detected_n{n}"] = ev.first(ev.variant(n), targets, _floor(lo), hi) is not None
        gt3.append(row)
    rec3 = _recall(gt3)
    res["gt3"] = {**rec3, "excluded": len(excluded),
                  "excluded_reasons": {k: sum(1 for e in excluded if e["reason"] == k) for k in {e["reason"] for e in excluded}},
                  "not_candidates": "Wimbledon finals (11-12 Jul) and US Open finals: no Wikipedia kick-off time in their "
                                    "articles; Champions League qualifiers: no match articles",
                  "ablation": {f"n{n}": _recall(gt3, f"detected_n{n}") for n in (2, 5)} | {"n3": rec3},
                  "verdict_h1b_3": ("inconclusive (< 5 matches)" if rec3["n"] < 5
                                    else "supported" if rec3["recall"] >= 0.90 else "rejected")}
    _write("phase2b_gt3_matches.csv", gt3)
    _write("phase2b_gt3_excluded.csv", [{"kickoff": e["kickoff"], "teams": " vs ".join(e["teams"]),
                                         "reason": e["reason"]} for e in excluded])
    (OUT / "phase2b_metrics.json").write_text(json.dumps(res, indent=1, default=str))
    return res


def _dist(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0}
    vals = sorted(vals)

    def q(p):
        return vals[min(len(vals) - 1, int(round(p * (len(vals) - 1))))]
    return {"n": len(vals), "median": statistics.median(vals), "p25": q(0.25), "p75": q(0.75), "min": vals[0],
            "max": vals[-1], "share_le_4h": sum(v <= 4 for v in vals) / len(vals)}


def _claims(table) -> dict[int, dict]:
    return {q: json.loads(c) for q, c in zip(table["qid"].to_pylist(), table["claims_json"].to_pylist())}


def _country(r: dict, claims: dict[int, dict]) -> int | None:
    if r["article_countries"]:
        return r["article_countries"][0]
    if r.get("region_is_us_state"):
        return 30  # United States
    for q in reversed(r["place_qids"]):  # region first
        c = claims.get(q, {})
        if set(c.get("P31", [])) & COUNTRY_CLASSES:
            return q
        if c.get("P17"):
            return c["P17"][0]
    return None
