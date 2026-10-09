"""Production scoring on top of the lake (STEP 3): daily baselines, hourly spikes, events, latest.json.

Lake paths (written only through lookedup.store, never git):

    data/spikes/year=YYYY/month=MM/day=DD.parquet   scored spike candidates (R1 or R2, R3 >= lowest ablation)
    data/events/year=YYYY/month=MM/day=DD.parquet   attention events by start day (primary config)
    data/events/languages/year=YYYY/month=MM/day=DD.parquet   one row per (event, language)
    data/latest.json                                last 24 h of events, top 50 by breadth then intensity
    data/scoring_state.json                         hours already scored

Baselines are NOT stored in the lake (ADR 0018): they live in a local directory
(``BASELINES_DIR``) that GitHub Actions persists with actions/cache, keyed by date. A missing
day is recomputed from the lake (at most one day per run) and never uploaded.

Self-healing like ingestion: each run scores every ingested hour of the catch-up window not
yet scored (at most ``max_hours``), provided that day's baselines exist or can be recomputed.
"""

from __future__ import annotations

import json
import logging
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from lookedup import db
from lookedup.analytics.config import load
from lookedup.analytics.entities import classify, died_near, fetch_claims
from lookedup.analytics.events import events_sql
from lookedup.analytics.production import daily_baselines_sql, score_hour_sql
from lookedup.dumps import session, utcnow
from lookedup.store import Manifest, Store, StoreConflict, day_path, write_parquet
from lookedup.settings import BASELINES_DIR, DATA_DIR, MAX_HOURS_PER_RUN, WINDOW_HOURS

log = logging.getLogger(__name__)

STATE_PATH = "data/scoring_state.json"
LATEST_PATH = "data/latest.json"
KEEP_BASELINE_DAYS = 3
BASELINE_BUCKETS = 16


def baselines_file(day: date, directory: Path = BASELINES_DIR) -> Path:
    return directory / f"day={day:%Y-%m-%d}.parquet"


def spikes_path(day: date) -> str:
    return day_path(datetime(day.year, day.month, day.day)).replace("data/hourly/", "data/spikes/")


def events_path(day: date) -> str:
    return day_path(datetime(day.year, day.month, day.day)).replace("data/hourly/", "data/events/")


def event_languages_path(day: date) -> str:
    return events_path(day).replace("data/events/", "data/events/languages/")


def _stg_view(con, files: list[Path], name: str = "src") -> None:
    paths = ", ".join(f"'{p}'" for p in files)
    con.execute(f"""CREATE OR REPLACE VIEW {name} AS SELECT ts_hour_start, ts_hour_start::DATE AS day,
        hour(ts_hour_start)::INT AS hour_of_day, (isodow(ts_hour_start) - 1) IN (5, 6) AS is_weekend,
        lang, title, views_desktop, views_mobile, views_desktop + views_mobile AS views,
        views_mobile / (views_desktop + views_mobile)::DOUBLE AS mobile_share
        FROM read_parquet([{paths}])""")


def _commit(store: Store, files: dict[str, Path], message: str) -> None:
    """Commit non-manifest files (scoring outputs). The manifest is passed through unchanged."""
    for attempt in range(5):
        try:
            store.commit(files, Manifest(), message, parent=store.head())
            return
        except StoreConflict:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"could not commit: {message}")


def build_baselines(store: Store, day: date, directory: Path = BASELINES_DIR) -> dict:
    """Baselines for ``day`` from the 28 day files before it, written to ``directory`` (never uploaded).

    Files older than KEEP_BASELINE_DAYS are pruned from ``directory``.
    """
    cfg = load()
    lo = day - timedelta(days=cfg.baseline["lookback_days"])
    manifest = store.read_manifest()
    directory.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        d = lo
        while d < day:
            p = day_path(datetime(d.year, d.month, d.day))
            if p in manifest.files:
                f = store.fetch(p, Path(tmp))
                if f:
                    files.append(f)
            d += timedelta(days=1)
        if not files:
            raise RuntimeError(f"no day files before {day}")
        con = db.connect()
        _stg_view(con, files)
        # BASELINE_BUCKETS passes over disjoint sets of titles keep memory and spill bounded (ADR 0018)
        parts = [db.arrow(con.sql(daily_baselines_sql("src", day, cfg, bucket=(i, BASELINE_BUCKETS),
                                                      include_prior=(i == 0))))
                 for i in range(BASELINE_BUCKETS)]
        table = pa.concat_tables(parts)
        out = baselines_file(day, directory)
        size = write_parquet(table, out)
    for old in directory.glob("day=*.parquet"):
        if old.stem.split("=")[1] < f"{day - timedelta(days=KEEP_BASELINE_DAYS):%Y-%m-%d}":
            old.unlink()
    log.info("baselines %s: %d slots, %d bytes, %d day files, %.0fs -> %s", day, table.num_rows, size, len(files),
             time.monotonic() - t0, out)
    return {"day": str(day), "rows": table.num_rows, "bytes": size, "day_files": len(files), "path": str(out)}


def _read_json(store: Store, path: str, tmp: Path) -> dict:
    p = store.fetch(path, tmp)
    return json.loads(p.read_text()) if p else {}


def qids_for(titles: list[tuple[str, str]]) -> dict[tuple[str, str], int]:
    """(lang, title) -> QID via the Wikidata API (sites=<lang>wiki), 50 titles per call."""
    out: dict[tuple[str, str], int] = {}
    by_lang: dict[str, list[str]] = {}
    for lang, title in titles:
        by_lang.setdefault(lang, []).append(title)
    for lang, ts in by_lang.items():
        site = lang.replace("-", "_") + "wiki"
        for i in range(0, len(ts), 50):
            chunk = ts[i:i + 50]
            r = session().get("https://www.wikidata.org/w/api.php", params={
                "action": "wbgetentities", "sites": site, "titles": "|".join(t.replace("_", " ") for t in chunk),
                "props": "sitelinks", "sitefilter": site, "format": "json"}, timeout=60)
            r.raise_for_status()
            for key, e in r.json().get("entities", {}).items():
                if key.startswith("Q") and "missing" not in e:
                    t = e.get("sitelinks", {}).get(site, {}).get("title")
                    if t:
                        out[(lang, t.replace(" ", "_"))] = int(key[1:])
            time.sleep(0.2)
    return out


def labels_for(qids: list[int], langs: list[str]) -> dict[int, dict[str, str]]:
    """QID -> {lang: title} for our languages, via the Wikidata API."""
    out: dict[int, dict[str, str]] = {}
    sites = {l.replace("-", "_") + "wiki": l for l in langs}
    for i in range(0, len(qids), 50):
        r = session().get("https://www.wikidata.org/w/api.php", params={
            "action": "wbgetentities", "ids": "|".join(f"Q{q}" for q in qids[i:i + 50]), "props": "sitelinks",
            "sitefilter": "|".join(sites), "format": "json"}, timeout=60)
        r.raise_for_status()
        for key, e in r.json().get("entities", {}).items():
            out[int(key[1:])] = {sites[s]: v["title"] for s, v in e.get("sitelinks", {}).items() if s in sites}
        time.sleep(0.2)
    return out


def score(store: Store, now: datetime | None = None, max_hours: int = MAX_HOURS_PER_RUN, langs: list[str] | None = None,
          hours: list[datetime] | None = None, baselines_dir: Path = BASELINES_DIR,
          recompute: bool = True) -> dict:
    """Score unscored ingested hours of the last 48 h (or exactly ``hours``); rebuild events and latest.json."""
    from lookedup.languages import active_codes

    cfg = load()
    now = now or utcnow()
    langs = langs or active_codes()
    manifest = store.read_manifest()
    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        state = _read_json(store, STATE_PATH, tmp / "state")
        scored = set(state.get("scored_hours", []))
        horizon = now - timedelta(hours=WINDOW_HOURS)
        if hours:
            pending = sorted(ts for ts in hours if ts in manifest.present())
        else:
            pending = sorted(ts for ts in manifest.present() if ts >= horizon and f"{ts:%Y-%m-%dT%H}" not in scored)
        bfiles: dict[date, Path | None] = {}
        recomputed = 0
        for d in sorted({ts.date() for ts in pending}, reverse=True):  # newest day first
            f = baselines_file(d, baselines_dir)
            if not f.exists() and recompute and recomputed < 1:
                log.info("no cached baselines for %s: recomputing from the lake", d)
                build_baselines(store, d, baselines_dir)
                recomputed += 1
            bfiles[d] = f if f.exists() else None
            if bfiles[d] is None:
                log.warning("no baselines for %s yet: its hours will be scored by a later run", d)
        todo = [ts for ts in pending if bfiles[ts.date()]][:max_hours]
        con = db.connect()
        new_spikes: dict[date, list[pa.Table]] = {}
        done = []
        for ts in todo:
            d = ts.date()
            bfile = bfiles[d]
            files = [f for f in (store.fetch(day_path(datetime(x.year, x.month, x.day)), tmp / "h")
                                 for x in (d - timedelta(days=1), d)) if f]
            _stg_view(con, files)
            con.execute(f"CREATE OR REPLACE VIEW bl AS SELECT * FROM read_parquet('{bfile}')")
            rel = con.sql(f"""SELECT * FROM ({score_hour_sql('src', 'bl', d, ts.hour, cfg)})
                              WHERE (r1 OR r2) AND surprise >= {cfg.min_r3_ablation}""")
            t = db.arrow(rel)
            new_spikes.setdefault(d, []).append(t)
            done.append(ts)
            log.info("scored hour=%s: %d spike candidates", f"{ts:%Y-%m-%dT%H}", t.num_rows)
        files: dict[str, Path] = {}
        # attach QIDs and merge new spike hours into the spike day files
        for d, tables in new_spikes.items():
            t = pa.concat_tables(tables) if tables else None
            keys = sorted(set(zip(t["lang"].to_pylist(), t["title"].to_pylist())))
            qmap = qids_for(keys) if keys else {}
            t = t.append_column("qid", pa.array([qmap.get(k) for k in zip(t["lang"].to_pylist(), t["title"].to_pylist())],
                                                pa.int64()))
            existing = store.fetch(spikes_path(d), tmp / "s")
            if existing:
                old = pq.read_table(existing)
                hours = pa.array(sorted(set(t["ts_hour_start"].to_pylist())), old.schema.field("ts_hour_start").type)
                old = old.filter(pc.invert(pc.is_in(old["ts_hour_start"], value_set=hours)))
                t = pa.concat_tables([old, t.cast(old.schema)])
            out = tmp / "out" / spikes_path(d)
            write_parquet(t, out)
            files[spikes_path(d)] = out
        # rebuild events from the spike files of the last two days
        days = sorted({now.date() - timedelta(days=1), now.date()})
        spike_files = [files.get(spikes_path(d)) or store.fetch(spikes_path(d), tmp / "s2") for d in days]
        spike_files = [p for p in spike_files if p]
        latest = {"generated_at": f"{now:%Y-%m-%dT%H:%M:%SZ}", "window_hours": 24, "events": [],
                  "single_language_events": []}
        if spike_files:
            paths = ", ".join(f"'{p}'" for p in spike_files)
            con.execute(f"""CREATE OR REPLACE VIEW sp AS SELECT * FROM read_parquet([{paths}], union_by_name = true)
                            WHERE NOT is_automated AND qid IS NOT NULL""")
            ev_sql, el_sql = events_sql("sp", cfg.event, scored="sp")
            events = db.arrow(con.sql(ev_sql))
            ev_langs = db.arrow(con.sql(el_sql))
            for d in days:
                lo, hi = datetime(d.year, d.month, d.day), datetime(d.year, d.month, d.day) + timedelta(days=1)
                for tbl, pathf in ((events, events_path), (ev_langs, event_languages_path)):
                    mask = pc.and_(pc.greater_equal(tbl["start_hour"], pa.scalar(lo, pa.timestamp("us"))),
                                   pc.less(tbl["start_hour"], pa.scalar(hi, pa.timestamp("us"))))
                    out = tmp / "out" / pathf(d)
                    write_parquet(tbl.filter(mask), out)
                    files[pathf(d)] = out
            all_recent = _latest(events, now, cfg, langs, tmp)
            # ADR 0019: single-language events are kept but listed separately
            latest["events"] = [e for e in all_recent if e["event_class"] != "single_language"][:50]
            latest["single_language_events"] = [e for e in all_recent if e["event_class"] == "single_language"][:50]
        out = tmp / "latest.json"
        out.write_text(json.dumps(latest, ensure_ascii=False, indent=1))
        files[LATEST_PATH] = out
        scored |= {f"{ts:%Y-%m-%dT%H}" for ts in done}
        cutoff = f"{now - timedelta(hours=WINDOW_HOURS + 24):%Y-%m-%dT%H}"
        st = tmp / "state.json"
        st.write_text(json.dumps({"scored_hours": sorted(s for s in scored if s >= cutoff)}, indent=1))
        files[STATE_PATH] = st
        _commit(store, files, f"data: score {len(done)} hour(s), {len(latest['events'])} event(s) in the last 24 h")
    return {"scored_hours": [f"{ts:%Y-%m-%dT%H}" for ts in done], "latest_events": len(latest["events"])}


def _latest(events: pa.Table, now: datetime, cfg, langs: list[str], tmp: Path) -> list[dict]:
    rows = [dict(zip(events.column_names, r)) for r in zip(*(events[c].to_pylist() for c in events.column_names))]
    rows = [r for r in rows if r["start_hour"] >= now - timedelta(hours=24)]
    rows.sort(key=lambda r: (-r["breadth"], -r["peak_intensity"]))
    if not rows:
        return []
    qids = [r["qid"] for r in rows]
    labels = labels_for(qids, langs)
    claims = fetch_claims(qids, DATA_DIR / "warehouse" / "entity_claims.parquet")
    cj = {q: json.loads(c) for q, c in zip(claims["qid"].to_pylist(), claims["claims_json"].to_pylist())}
    out = []
    for r in rows:
        c = cj.get(r["qid"], {})
        is_human = int(cfg.raw["human_class"][1:]) in c.get("P31", [])
        cat = "death" if is_human and died_near(c, r["start_hour"].date(), cfg) else classify(c, cfg)
        out.append({"qid": f"Q{r['qid']}", "start_hour": f"{r['start_hour']:%Y-%m-%dT%H}:00Z",
                    "lead_lang": r["lead_lang"], "breadth": r["breadth"],
                    "peak_intensity": round(r["peak_intensity"], 1), "excess_views": int(r["excess_views"] or 0),
                    "languages": r["languages"], "category": cat, "event_class": r.get("event_class"),
                    "lead_excess_share": round(r.get("lead_excess_share") or 0, 3),
                    "labels": {l: t for l, t in sorted(labels.get(r["qid"], {}).items())}})
    return out
