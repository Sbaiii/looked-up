"""Q5: do pageview spikes precede (or match) the news?

For each event:
  * window  = 24 hourly dump files starting at `t0` (file named HH covers HH-1..HH),
  * baseline = same hours 24 h earlier, from pageview_complete daily file(s)
    (hourly per-article counts; avoids downloading 24 more hourly files),
  * titles   = resolved via Wikidata sitelinks, plus every redirect to them
    (new event articles get renamed; views land on whatever title was live).
Spike = first hour where views >= 5 x baseline (same hour, previous day) and views >= 20.

Usage: .venv/bin/python spike/q5_spike_test.py
Writes docs/q5_<event>_hourly.csv and docs/q5_detection_summary.csv.
"""

from __future__ import annotations

import bz2
import csv
import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import duckdb

from common import DERIVED, DOCS, RAW, download, hourly_url, session

UTC = timezone.utc
RATIO, FLOOR = 5.0, 20
PVC = "https://dumps.wikimedia.org/other/pageview_complete"

EVENTS = [
    {
        "key": "harald_v_death",
        "label": "Death of King Harald V of Norway",
        "enwiki": "Harald V",
        "event_utc": datetime(2026, 8, 28, 4, 35, tzinfo=UTC),
        "public_utc": datetime(2026, 8, 28, 6, 35, tzinfo=UTC),
        "source": "en.wikipedia 'Death and state funeral of Harald V': died 06:35 CEST, Royal House announced 08:35 CEST",
        "t0": datetime(2026, 8, 28, 0, tzinfo=UTC),
        "langs": ["en", "no", "sv", "da", "de", "fr", "es", "it", "ru", "ja"],
    },
    {
        "key": "colombia_earthquake",
        "label": "M7.4 earthquake, Chocó, Colombia",
        "enwiki": "2026 Colombia earthquake",
        "extra_enwiki": ["Chocó Department"],
        "event_utc": datetime(2026, 8, 10, 12, 34, tzinfo=UTC),
        "public_utc": datetime(2026, 8, 10, 12, 34, tzinfo=UTC),
        "source": "en.wikipedia '2026 Colombia earthquake' infobox: 2026-08-10 12:34:28 UTC (07:34 COT)",
        "t0": datetime(2026, 8, 10, 0, tzinfo=UTC),
        "langs": ["en", "es", "fr", "de", "pt", "it", "ru", "ja", "zh", "ar"],
    },
    {
        "key": "us_open_final_zverev",
        "label": "US Open men's final won by Alexander Zverev",
        "enwiki": "Alexander Zverev",
        "event_utc": datetime(2026, 9, 13, 21, 48, tzinfo=UTC),
        "public_utc": datetime(2026, 9, 13, 21, 48, tzinfo=UTC),
        "start_utc": datetime(2026, 9, 13, 18, 0, tzinfo=UTC),
        "source": "Start 2 p.m. ET = 18:00 UTC (Al Jazeera). End ~21:48 UTC: de.wikipedia edit at 21:49 UTC "
                  "'er hat vor 20 Sekunden die us open gewonnen'; first Reuters wire on KSL 21:55 UTC",
        "t0": datetime(2026, 9, 13, 12, tzinfo=UTC),
        "langs": ["en", "de", "fr", "es", "it", "ru", "ja", "pl", "pt", "zh"],
    },
]


def sitelinks(enwiki: str) -> tuple[str, dict[str, str]]:
    r = session.get("https://www.wikidata.org/w/api.php", params={
        "action": "wbgetentities", "sites": "enwiki", "titles": enwiki, "props": "sitelinks",
        "format": "json", "redirects": "yes"}, timeout=30).json()
    ent = next(iter(r["entities"].values()))
    return ent["id"], {k[:-4]: v["title"] for k, v in ent.get("sitelinks", {}).items() if k.endswith("wiki")}


def redirects(lang: str, title: str) -> list[str]:
    out, cont = [title.replace(" ", "_")], {}
    while True:
        r = session.get(f"https://{lang}.wikipedia.org/w/api.php", params={
            "action": "query", "prop": "redirects", "titles": title, "rdlimit": "max",
            "rdnamespace": 0, "format": "json", **cont}, timeout=30).json()
        for p in r.get("query", {}).get("pages", {}).values():
            out += [x["title"].replace(" ", "_") for x in p.get("redirects", [])]
        if "continue" not in r:
            return out
        cont = r["continue"]


def build_targets(ev: dict) -> dict:
    """{(lang, title_variant): (entity_label, canonical_title)}"""
    targets, meta = {}, {}
    for en_title in [ev["enwiki"]] + ev.get("extra_enwiki", []):
        qid, links = sitelinks(en_title)
        meta[en_title] = {"qid": qid, "titles": {}}
        for lang in ev["langs"]:
            lang_key = lang.replace("-", "_")
            if lang_key not in links:
                continue
            canon = links[lang_key]
            meta[en_title]["titles"][lang] = canon
            for t in redirects(lang, canon):
                targets[(lang, t)] = (en_title, canon.replace(" ", "_"))
    return {"targets": targets, "meta": meta}


def window_hours(t0: datetime) -> list[datetime]:
    return [t0 + timedelta(hours=i) for i in range(24)]


def fetch_hourly(hours: list[datetime]) -> list:
    """Download hourly files; file for hour-start h is named h+1h."""
    def one(h):
        url = hourly_url(h + timedelta(hours=1))
        return download(url, RAW / "pageviews" / url.rsplit("/", 1)[1])[0]
    with ThreadPoolExecutor(int(os.environ.get("DL_WORKERS", "1"))) as ex:
        return list(ex.map(one, hours))


def hourly_counts(paths: list, hours: list[datetime], targets: dict) -> dict:
    con = duckdb.connect()
    con.execute("CREATE TABLE t(lang VARCHAR, title VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?, ?)", list(targets.keys()))
    out = {}
    for h, p in zip(hours, paths):
        rows = con.execute(f"""
            SELECT split_part(project, '.', 1) AS lang, page_title, sum(views)
            FROM read_csv('{p}', delim=' ', header=false, quote='', escape='', auto_detect=false,
                 columns={{'project':'VARCHAR','page_title':'VARCHAR','views':'BIGINT','bytes':'BIGINT'}},
                 ignore_errors=true) pv
            JOIN t ON t.lang = split_part(pv.project, '.', 1) AND t.title = pv.page_title
            WHERE regexp_matches(project, '^[a-z-]+(\\.m)?$')
            GROUP BY 1, 2
        """).fetchall()
        for lang, title, v in rows:
            out[(h, lang, title)] = int(v)
    return out


def pvc_counts(day: datetime, targets: dict) -> dict:
    """Stream a pageview_complete user file and pull hourly counts for target titles."""
    digest = hashlib.sha1(json.dumps(sorted(targets)).encode()).hexdigest()[:10]
    cache = DERIVED / f"pvc_{day:%Y%m%d}_{digest}.json"
    if cache.exists():
        raw = json.loads(cache.read_text())
        return {(datetime.fromisoformat(h), l, t): v for h, l, t, v in raw}
    url = f"{PVC}/{day:%Y}/{day:%Y-%m}/pageviews-{day:%Y%m%d}-user.bz2"
    dest = RAW / "pageview_complete" / url.rsplit("/", 1)[1]
    download(url, dest)
    want = {(f"{l}.wikipedia".encode(), t.encode()) for l, t in targets}
    out: dict = {}
    with bz2.open(dest, "rb") as f:
        for line in f:
            parts = line.split(b" ", 2)
            if len(parts) < 3 or (parts[0], parts[1]) not in want:
                continue
            fields = line.rstrip(b"\n").split(b" ")
            lang = fields[0].decode().split(".")[0]
            title = fields[1].decode()
            for hh, c in re.findall(rb"([A-X])(\d+)", fields[-1]):
                k = (day + timedelta(hours=hh[0] - 65), lang, title)
                out[k] = out.get(k, 0) + int(c)
    cache.write_text(json.dumps([(h.isoformat(), l, t, v) for (h, l, t), v in out.items()]))
    return out


def analyse(ev: dict) -> list[dict]:
    tg = build_targets(ev)
    targets = tg["targets"]
    hours = window_hours(ev["t0"])
    paths = fetch_hourly(hours)
    cur = hourly_counts(paths, hours, targets)
    base_days = sorted({(h - timedelta(days=1)).replace(hour=0) for h in hours})
    base: dict = {}
    for d in base_days:
        base.update(pvc_counts(d, targets))

    # collapse redirects onto (entity, lang)
    def collapse(counts):
        agg = {}
        for (h, lang, title), v in counts.items():
            ent, canon = targets[(lang, title)]
            agg[(h, ent, lang)] = agg.get((h, ent, lang), 0) + v
        return agg

    cur_a, base_a = collapse(cur), collapse(base)
    rows, summary = [], []
    for ent, m in tg["meta"].items():
        for lang, canon in m["titles"].items():
            first = None
            for h in hours:
                v = cur_a.get((h, ent, lang), 0)
                b = base_a.get((h - timedelta(days=1), ent, lang), 0)
                spike = v >= FLOOR and v >= RATIO * b
                if spike and first is None and h + timedelta(hours=1) > ev["event_utc"] - timedelta(hours=6):
                    first = h
                rows.append({"hour_start_utc": f"{h:%Y-%m-%d %H:00}", "entity": ent, "qid": m["qid"],
                             "lang": lang, "title": canon, "views": v, "baseline_prev_day": b,
                             "ratio": round(v / b, 1) if b else "", "spike": int(spike)})
            delay = round((first - ev["event_utc"]).total_seconds() / 3600, 2) if first else None
            summary.append({"event": ev["key"], "entity": ent, "qid": m["qid"], "lang": lang, "title": canon,
                            "event_utc": f"{ev['event_utc']:%Y-%m-%d %H:%M}",
                            "public_utc": f"{ev['public_utc']:%Y-%m-%d %H:%M}",
                            "first_spike_hour_utc": f"{first:%Y-%m-%d %H:00}" if first else "",
                            "hour_start_minus_event_h": delay,
                            # data for hour h is complete at h+1h; dumps then publish ~2.2 h later (median lag)
                            "data_available_after_event_h": round(delay + 1 + 134 / 60, 1) if delay is not None else None,
                            "peak_views_hour": max((cur_a.get((h, ent, lang), 0) for h in hours), default=0)})
    with open(DOCS / f"q5_{ev['key']}_hourly.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # cross-check: hours covered by both the hourly dumps and a pageview_complete file
    overlap = [(k, v, base[k]) for k, v in cur.items() if k in base]
    if overlap:
        same = sum(1 for _, a, b in overlap if a == b)
        print(f"  cross-check hourly vs pageview_complete: {same}/{len(overlap)} identical")
        ev["crosscheck"] = {"pairs": len(overlap), "identical": same,
                            "max_abs_diff": max(abs(a - b) for _, a, b in overlap)}
    return summary


def main() -> None:
    allsum = []
    for ev in EVENTS:
        print("==", ev["label"])
        s = analyse(ev)
        for r in s:
            print("  ", r["entity"][:22], r["lang"], r["first_spike_hour_utc"], r["hour_start_minus_event_h"],
                  r["peak_views_hour"])
        allsum += s
    with open(DOCS / "q5_detection_summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(allsum[0].keys()))
        w.writeheader()
        w.writerows(allsum)
    meta = [{k: (str(v) if isinstance(v, datetime) else v) for k, v in ev.items()} for ev in EVENTS]
    (DERIVED / "q5_events.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
