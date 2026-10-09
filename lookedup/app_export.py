"""Small JSON exports for the web app (ADR 0022), written to the lake under data/app/.

    data/app/today.json            events that started in the last 24 h
    data/app/days/YYYY-MM-DD.json  events that started on one UTC day
    data/app/stats.json            per-day summaries for the last 90 days, totals and an hourly timeline

Every file carries ``schema_version``. Events are product events (ADR 0021: >= 2 languages, tiered).
A day or today file holds the top TOP_EVENTS multi-language events by breadth, plus each language's top
PER_LANGUAGE events (for the "what each language looked up" panel), plus single-language events
(top SINGLE_PER_LANGUAGE per lead language, the "only here" lists). Summaries in stats.json count all events.

Two sources feed the same builders: the warehouse marts for the batch period (backfill) and the
production spike files for live hours (the hourly job).
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

from lookedup import db

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
APP_PREFIX = "data/app"
TOP_EVENTS = 200
PER_LANGUAGE = 5
SINGLE_PER_LANGUAGE = 10
SPARK_BEFORE = 24       # sparkline: 48 hourly points from start - 24 h to start + 23 h
SPARK_HOURS = 48
STATS_DAYS = 90

_DISAMBIG = re.compile(r"\s+\([^)]*\)$")


def day_file(d: date) -> str:
    return f"{APP_PREFIX}/days/{d:%Y-%m-%d}.json"


def label_from_title(title: str) -> str:
    """'Mike_Burton_(swimmer)' -> 'Mike Burton'."""
    return _DISAMBIG.sub("", title.replace("_", " "))


_URL_ESCAPES = str.maketrans({"%": "%25", "?": "%3F", "#": "%23", '"': "%22", " ": "_"})


def wiki_url(lang: str, title: str) -> str:
    """Article URL as an IRI: non-ASCII stays readable (browsers encode it), only URL syntax is escaped."""
    return f"https://{lang}.wikipedia.org/wiki/{title.translate(_URL_ESCAPES)}"


def _iso(ts: datetime) -> str:
    return f"{ts:%Y-%m-%dT%H}:00Z"


def dump(payload: dict, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    return len(text.encode())


# ---------------------------------------------------------------- selection and payloads

def select(events: list[dict], langs: dict[str, list[dict]]) -> tuple[list[dict], list[dict]]:
    """(multi, single) events to publish for one period. ``langs`` maps event_id -> language rows."""
    multi = sorted((e for e in events if e["event_class"] != "single_language"),
                   key=lambda e: (-e["breadth"], -(e["excess_views"] or 0), e["event_id"]))
    keep = {e["event_id"] for e in multi[:TOP_EVENTS]}
    by_lang: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for e in multi:
        for r in langs.get(e["event_id"], []):
            by_lang[r["lang"]].append((-(r["excess_views"] or 0), e["event_id"]))
    for rows in by_lang.values():
        keep |= {eid for _, eid in sorted(rows)[:PER_LANGUAGE]}
    single = sorted((e for e in events if e["event_class"] == "single_language"),
                    key=lambda e: (-(e["excess_views"] or 0), e["event_id"]))
    per_lead: Counter = Counter()
    singles = []
    for e in single:
        if per_lead[e["lead_lang"]] < SINGLE_PER_LANGUAGE:
            per_lead[e["lead_lang"]] += 1
            singles.append(e)
    return [e for e in multi if e["event_id"] in keep], singles


def event_obj(e: dict, langs: list[dict], titles: dict[str, str], spark: list[int] | None,
              category: str | None) -> dict:
    rows = sorted(langs, key=lambda r: (r["spread_lag_hours"], r["lang"]))
    return {
        "id": e["event_id"], "qid": f"Q{e['qid']}", "start": _iso(e["start_hour"]),
        "tier": e["tier"], "class": e["event_class"], "breadth": e["breadth"], "lead": e["lead_lang"],
        "category": category or "other",
        "excess": int(e["excess_views"] or 0), "peak": round(e["peak_intensity"], 1),
        "spread_h": int(e["max_spread_lag_hours"] or 0),
        "labels": {l: label_from_title(t) for l, t in sorted(titles.items())},
        "urls": {l: wiki_url(l, t) for l, t in sorted(titles.items())},
        "langs": [{"lang": r["lang"], "first": _iso(r["first_spike"]), "lag": int(r["spread_lag_hours"]),
                   "surprise": round(r["peak_surprise"], 1), "excess": int(r["excess_views"] or 0)} for r in rows],
        "spark": spark,
    }


def summary(events: list[dict], langs: dict[str, list[dict]]) -> dict:
    """Counts over ALL events of a period (not only the published ones)."""
    tiers: Counter = Counter()
    hourly = [0] * 24
    per_lang: dict[str, dict] = defaultdict(lambda: {"events": 0, "lead": 0, "excess": 0, "only_here": 0})
    for e in events:
        if e["event_class"] == "single_language":
            per_lang[e["lead_lang"]]["only_here"] += 1
            continue
        tiers[e["tier"]] += 1
        hourly[e["start_hour"].hour] += 1
        per_lang[e["lead_lang"]]["lead"] += 1
        for r in langs.get(e["event_id"], []):
            per_lang[r["lang"]]["events"] += 1
            per_lang[r["lang"]]["excess"] += int(r["excess_views"] or 0)
    return {"events": sum(tiers.values()), "single_language": sum(1 for e in events if e["event_class"] == "single_language"),
            "tiers": {t: tiers.get(t, 0) for t in ("noticed", "international", "planetary")},
            "hourly": hourly, "languages": dict(sorted(per_lang.items()))}


def period_payload(kind: str, events: list[dict], langs: dict[str, list[dict]], titles: dict[int, dict[str, str]],
                   sparks: dict[str, list[int]], categories: dict[int, str], generated_at: datetime, **extra) -> dict:
    multi, single = select(events, langs)
    obj = lambda e: event_obj(e, langs.get(e["event_id"], []), titles.get(e["qid"], {}), sparks.get(e["event_id"]),
                              categories.get(e["qid"]))
    return {"schema_version": SCHEMA_VERSION, "kind": kind, "generated_at": f"{generated_at:%Y-%m-%dT%H:%M:%SZ}",
            **extra, "summary": summary(events, langs),
            "events": [obj(e) for e in multi], "single_language_events": [obj(e) for e in single]}


def stats_payload(days: dict[str, dict], generated_at: datetime, languages: list[str]) -> dict:
    """Totals over the per-day summaries of the last STATS_DAYS days."""
    keys = sorted(days)[-STATS_DAYS:]
    days = {k: days[k] for k in keys}
    tiers: Counter = Counter()
    per_lang: dict[str, Counter] = defaultdict(Counter)
    for s in days.values():
        tiers.update(s["tiers"])
        for l, c in s["languages"].items():
            per_lang[l].update(c)
    total = sum(tiers.values())
    return {
        "schema_version": SCHEMA_VERSION, "kind": "stats", "generated_at": f"{generated_at:%Y-%m-%dT%H:%M:%SZ}",
        "first_day": keys[0] if keys else None, "last_day": keys[-1] if keys else None,
        "languages": languages, "events": total,
        "single_language": sum(s["single_language"] for s in days.values()),
        "tiers": {t: tiers.get(t, 0) for t in ("noticed", "international", "planetary")},
        "per_language": {l: {**dict(c), "lead_share": round(c["lead"] / total, 4) if total else 0}
                         for l, c in sorted(per_lang.items())},
        # one row per day: event counts per start hour (UTC), and the day's tier counts
        "timeline": [{"day": k, "hourly": s["hourly"], "tiers": s["tiers"], "single_language": s["single_language"]}
                     for k, s in days.items()],
        "days": days,
    }


# ---------------------------------------------------------------- inputs

def rows(rel: duckdb.DuckDBPyRelation) -> list[dict]:
    cols = rel.columns
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def group_langs(lang_rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in lang_rows:
        out[r["event_id"]].append(r)
    return out


def sparklines(con: duckdb.DuckDBPyConnection, hourly_files: list[Path], events: list[dict],
               titles: dict[int, dict[str, str]], last_hour: datetime | None = None) -> dict[str, list[int | None]]:
    """event_id -> total views across the entity's articles (our languages), 48 hourly points.

    Points after ``last_hour`` (the newest ingested hour) are None: not known yet."""
    if not events or not hourly_files:
        return {}
    con.execute("CREATE OR REPLACE TEMP TABLE _k(qid BIGINT, lang VARCHAR, title VARCHAR)")
    con.executemany("INSERT INTO _k VALUES (?, ?, ?)",
                    [(q, l, t.replace(" ", "_")) for q in {e["qid"] for e in events} for l, t in titles.get(q, {}).items()])
    con.execute("CREATE OR REPLACE TEMP TABLE _ev(event_id VARCHAR, qid BIGINT, start_hour TIMESTAMP)")
    con.executemany("INSERT INTO _ev VALUES (?, ?, ?)", [(e["event_id"], e["qid"], e["start_hour"]) for e in events])
    paths = ", ".join(f"'{p}'" for p in hourly_files)
    res = con.sql(f"""
        WITH h AS (
            SELECT k.qid, h.ts_hour_start, sum(h.views_desktop + h.views_mobile) AS views
            FROM read_parquet([{paths}]) h JOIN _k k USING (lang, title) GROUP BY ALL
        )
        SELECT ev.event_id, date_diff('hour', ev.start_hour - INTERVAL {SPARK_BEFORE} HOUR, h.ts_hour_start) AS i,
               h.views
        FROM _ev ev JOIN h ON h.qid = ev.qid
         AND h.ts_hour_start >= ev.start_hour - INTERVAL {SPARK_BEFORE} HOUR
         AND h.ts_hour_start < ev.start_hour + INTERVAL {SPARK_HOURS - SPARK_BEFORE} HOUR
    """).fetchall()
    out: dict[str, list[int | None]] = {}
    for e in events:
        first = e["start_hour"] - timedelta(hours=SPARK_BEFORE)
        out[e["event_id"]] = [None if last_hour and first + timedelta(hours=i) > last_hour else 0
                              for i in range(SPARK_HOURS)]
    for eid, i, v in res:
        out[eid][i] = int(v)
    return out


def published(events: list[dict], langs: dict[str, list[dict]]) -> list[dict]:
    multi, single = select(events, langs)
    return multi + single


EVENT_COLS = ("event_id, qid, start_hour, lead_lang, breadth, peak_intensity, excess_views, max_spread_lag_hours, "
              "event_class, tier")
LANG_COLS = "event_id, lang, first_spike, spread_lag_hours, peak_surprise, excess_views"


def events_from_spikes(con: duckdb.DuckDBPyConnection, spike_files: list[Path]) -> tuple[list[dict], list[dict]]:
    """Product events (and their language rows) from production spike files."""
    from lookedup.analytics.config import load
    from lookedup.analytics.events import events_sql

    if not spike_files:
        return [], []
    paths = ", ".join(f"'{p}'" for p in spike_files)
    con.execute(f"""CREATE OR REPLACE VIEW _sp AS SELECT * FROM read_parquet([{paths}], union_by_name = true)
                    WHERE NOT is_automated AND qid IS NOT NULL""")
    ev_sql, el_sql = events_sql("_sp", load().product_event, scored="_sp")
    return (rows(con.sql(f"SELECT {EVENT_COLS} FROM ({ev_sql})")),
            rows(con.sql(f"SELECT {LANG_COLS} FROM ({el_sql})")))


def titles_from_sitelinks(con: duckdb.DuckDBPyConnection, sitelinks: Path, qids: set[int],
                          langs: list[str]) -> dict[int, dict[str, str]]:
    con.execute("CREATE OR REPLACE TEMP TABLE _q(qid BIGINT)")
    con.executemany("INSERT INTO _q VALUES (?)", [(q,) for q in qids])
    out: dict[int, dict[str, str]] = defaultdict(dict)
    lang_list = ", ".join(f"'{l}'" for l in langs)
    for q, l, t in con.sql(f"""SELECT s.qid, s.lang, s.title FROM read_parquet('{sitelinks}') s
                               JOIN _q USING (qid) WHERE s.lang IN ({lang_list})""").fetchall():
        out[q][l] = t
    return dict(out)


def titles_from_api(qids: set[int], langs: list[str]) -> dict[int, dict[str, str]]:
    from lookedup.scorer import labels_for

    return {q: {l: t.replace(" ", "_") for l, t in ts.items()} for q, ts in labels_for(sorted(qids), langs).items()}


def categories_for(events: list[dict]) -> dict[int, str]:
    """QID -> category (death if a human died near the event start), via cached Wikidata claims."""
    from lookedup.analytics.config import load
    from lookedup.analytics.entities import classify, died_near, fetch_claims
    from lookedup.settings import DATA_DIR

    if not events:
        return {}
    cfg = load()
    qids = sorted({e["qid"] for e in events})
    claims = fetch_claims(qids, DATA_DIR / "warehouse" / "entity_claims.parquet")
    cj = {q: json.loads(c) for q, c in zip(claims["qid"].to_pylist(), claims["claims_json"].to_pylist())}
    human = int(cfg.raw["human_class"][1:])
    out = {}
    for e in events:
        c = cj.get(e["qid"], {})
        died = human in c.get("P31", []) and died_near(c, e["start_hour"].date(), cfg)
        out[e["qid"]] = "death" if died else classify(c, cfg)
    return out


def by_day(events: list[dict]) -> dict[date, list[dict]]:
    out: dict[date, list[dict]] = defaultdict(list)
    for e in events:
        out[e["start_hour"].date()].append(e)
    return out


def write_day(con, out_dir: Path, d: date, events: list[dict], langs: dict[str, list[dict]],
              titles: dict[int, dict[str, str]], categories: dict[int, str], hourly_files: list[Path],
              now: datetime, last_hour: datetime | None = None) -> dict:
    sparks = sparklines(con, hourly_files, published(events, langs), titles, last_hour)
    payload = period_payload("day", events, langs, titles, sparks, categories, now, date=f"{d:%Y-%m-%d}")
    size = dump(payload, out_dir / day_file(d))
    log.info("app day %s: %d events, %d published, %d bytes", d, len(events),
             len(payload["events"]) + len(payload["single_language_events"]), size)
    return payload["summary"]


def _today_payload(con, events, langs, titles, categories, hourly_files, now, last_hour) -> dict:
    recent = [e for e in events if e["start_hour"] >= now - timedelta(hours=24)]
    sparks = sparklines(con, hourly_files, published(recent, langs), titles, last_hour)
    return period_payload("today", recent, langs, titles, sparks, categories, now, window_hours=24,
                          last_hour=_iso(last_hour) if last_hour else None)


def _update_stats(old: dict, summaries: dict[str, dict], now: datetime, languages: list[str]) -> dict:
    days = dict(old.get("days", {})) if old.get("schema_version") == SCHEMA_VERSION else {}
    days.update(summaries)
    return stats_payload(days, now, languages)


def backfill(store, out_dir: Path, now: datetime | None = None, languages: list[str] | None = None) -> dict:
    """Write every day file (warehouse period, then live days from production spikes), today.json and stats.json
    into ``out_dir`` (mirroring lake paths). Uses the local lake mirror for sparklines and titles."""
    from lookedup.dumps import utcnow
    from lookedup.languages import active_codes
    from lookedup.scorer import spikes_path
    from lookedup.settings import LOCAL_LAKE_DIR
    from lookedup.store import day_path
    from lookedup.warehouse import WAREHOUSE_DB

    now = now or utcnow()
    languages = languages or active_codes()
    con = db.connect()
    con.execute(f"ATTACH '{WAREHOUSE_DB}' AS wh (READ_ONLY)")
    events = rows(con.sql(f"SELECT {EVENT_COLS}, category FROM wh.main.fct_app_events"))
    lang_rows = rows(con.sql(f"SELECT {LANG_COLS} FROM wh.main.fct_app_event_languages"))
    categories = {e["qid"]: e["category"] for e in events}
    wh_end = max(e["start_hour"] for e in events).date()
    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        live_days = [wh_end + timedelta(days=i) for i in range(1, (now.date() - wh_end).days + 1)]
        spike_files = [f for f in (store.fetch(spikes_path(d), tmp) for d in live_days) if f]
        ev2, lr2 = events_from_spikes(con, spike_files)
        ev2 = [e for e in ev2 if e["start_hour"].date() > wh_end]
        keep = {e["event_id"] for e in ev2}
        lr2 = [r for r in lr2 if r["event_id"] in keep]
        langs_by = group_langs(lang_rows + lr2)
        events += ev2
        days = by_day(events)
        pub = [e for d in days for e in published(days[d], langs_by)]
        categories |= categories_for([e for e in pub if e["event_id"] in keep])
        titles = titles_from_sitelinks(con, LOCAL_LAKE_DIR / "data" / "wikidata" / "sitelinks.parquet",
                                       {e["qid"] for e in pub}, languages)

        def hourly(d0: date, d1: date) -> list[Path]:
            fs = [LOCAL_LAKE_DIR / day_path(datetime(x.year, x.month, x.day))
                  for x in (d0 + timedelta(days=i) for i in range((d1 - d0).days + 1))]
            return [f for f in fs if f.exists()]

        newest = hourly(now.date() - timedelta(days=1), now.date())
        last_hour = con.sql(f"SELECT max(ts_hour_start) FROM read_parquet([{', '.join(repr(str(f)) for f in newest)}])"
                            ).fetchone()[0] if newest else None
        summaries = {}
        for d in sorted(days):
            summaries[f"{d:%Y-%m-%d}"] = write_day(con, out_dir, d, days[d], langs_by, titles, categories,
                                                   hourly(d - timedelta(days=1), d + timedelta(days=1)), now, last_hour)
        today = _today_payload(con, events, langs_by, titles, categories,
                               hourly(now.date() - timedelta(days=2), now.date()), now, last_hour)
        dump(today, out_dir / APP_PREFIX / "today.json")
        stats = stats_payload(summaries, now, languages)
        dump(stats, out_dir / APP_PREFIX / "stats.json")
    return {"days": len(summaries), "first": min(summaries), "last": max(summaries), "events": stats["events"],
            "tiers": stats["tiers"], "single_language": stats["single_language"]}


def export_live(store, now: datetime | None = None, languages: list[str] | None = None) -> dict:
    """Hourly: rebuild today.json, the day files of yesterday and today, and stats.json; commit to the lake."""
    from lookedup.dumps import utcnow
    from lookedup.languages import active_codes
    from lookedup.scorer import _commit, _read_json, spikes_path
    from lookedup.store import day_path

    now = now or utcnow()
    languages = languages or active_codes()
    today = now.date()
    con = db.connect()
    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        span = [today - timedelta(days=i) for i in (2, 1, 0)]
        spike_files = [f for f in (store.fetch(spikes_path(d), tmp / "s") for d in span) if f]
        events, lang_rows = events_from_spikes(con, spike_files)
        events = [e for e in events if e["start_hour"].date() >= today - timedelta(days=1)]
        langs_by = group_langs(lang_rows)
        hourly_files = [f for f in (store.fetch(day_path(datetime(d.year, d.month, d.day)), tmp / "h") for d in span) if f]
        present = store.read_manifest().present()
        last_hour = max(present) if present else None
        days = by_day(events)
        recent = [e for e in events if e["start_hour"] >= now - timedelta(hours=24)]
        pub = {e["event_id"]: e for d in days for e in published(days[d], langs_by)}
        pub |= {e["event_id"]: e for e in published(recent, langs_by)}
        titles = titles_from_api({e["qid"] for e in pub.values()}, languages)
        categories = categories_for(list(pub.values()))
        out = tmp / "out"
        files: dict[str, Path] = {}
        summaries = {}
        for d in (today - timedelta(days=1), today):
            summaries[f"{d:%Y-%m-%d}"] = write_day(con, out, d, days.get(d, []), langs_by, titles, categories,
                                                   hourly_files, now, last_hour)
            files[day_file(d)] = out / day_file(d)
        dump(_today_payload(con, events, langs_by, titles, categories, hourly_files, now, last_hour),
             out / APP_PREFIX / "today.json")
        files[f"{APP_PREFIX}/today.json"] = out / APP_PREFIX / "today.json"
        stats = _update_stats(_read_json(store, f"{APP_PREFIX}/stats.json", tmp / "st"), summaries, now, languages)
        dump(stats, out / APP_PREFIX / "stats.json")
        files[f"{APP_PREFIX}/stats.json"] = out / APP_PREFIX / "stats.json"
        _commit(store, files, f"data: app exports, {len(recent)} event(s) in the last 24 h")
    return {"today_events": len(recent), "days": sorted(summaries)}
