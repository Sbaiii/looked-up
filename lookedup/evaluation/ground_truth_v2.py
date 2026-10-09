"""Phase 2b ground truths (docs/prereg_phase2b.md): deaths, earthquakes, scheduled matches.

Each builder returns rows with a reference time, a window, and one or more target QIDs. Network
access: English Wikipedia (lists, revisions, template expansion), Wikidata Query Service, USGS FDSN.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from datetime import date, datetime, timedelta, timezone

import requests

from lookedup.dumps import session
from lookedup.evaluation.ground_truth import resolve_qids

log = logging.getLogger(__name__)

EN_API = "https://en.wikipedia.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
USGS = "https://earthquake.usgs.gov/fdsnws/event/1/query"
DEATH_WORDS = re.compile(r"(?i)\b(death|died|dies|dead|passed away|passing|rip|deceased|dod|obituary)\b")


def _get(url: str, params: dict, retries: int = 5, **kw):
    for attempt in range(retries):
        try:
            r = session().get(url, params=params, timeout=60, **kw)
            r.raise_for_status()
            time.sleep(0.3)
            return r
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            log.warning("%s failed (%s), retry", url, e)
            time.sleep(3 * (attempt + 1))


def _raw(title: str) -> str:
    r = _get("https://en.wikipedia.org/w/index.php", {"title": title, "action": "raw"})
    return r.text


# ---------------------------------------------------------------- GT1 deaths

_DAY = re.compile(r"^===\s*(\d{1,2})\s*===\s*$")
_FIRST_LINK = re.compile(r"\[\[([^\[\]|#]+)(?:\|[^\]]*)?\]\]")


def parse_deaths(wikitext: str, year: int, month: int) -> list[dict]:
    """[{date, title, text}] for every bullet under a day heading of a 'Deaths in <Month> <Year>' page."""
    out, day = [], None
    for line in wikitext.splitlines():
        m = _DAY.match(line.strip())
        if m:
            day = int(m.group(1))
            continue
        if day is None or not line.startswith("*"):
            continue
        link = _FIRST_LINK.search(line)
        if link:
            out.append({"date": date(year, month, day), "title": link.group(1).strip(), "text": line[:200]})
    return out


def announcement_proxy(title: str, day: date) -> datetime | None:
    """Earliest enwiki revision in [day-1, day+2) whose edit summary mentions death."""
    start = datetime.combine(day - timedelta(days=1), datetime.min.time())
    end = start + timedelta(days=3)
    r = _get(EN_API, {"action": "query", "prop": "revisions", "titles": title, "redirects": 1, "rvdir": "newer",
                      "rvstart": f"{start:%Y-%m-%dT%H:%M:%SZ}", "rvend": f"{end:%Y-%m-%dT%H:%M:%SZ}",
                      "rvlimit": 100, "rvprop": "timestamp|comment", "format": "json", "formatversion": 2})
    pages = r.json().get("query", {}).get("pages", [])
    for rev in (pages[0].get("revisions", []) if pages else []):
        if DEATH_WORDS.search(rev.get("comment", "")):
            return datetime.fromisoformat(rev["timestamp"].replace("Z", ""))
    return None


def deaths(months: list[tuple[int, int]], n_languages: dict[int, int], min_languages: int) -> list[dict]:
    rows = []
    for year, month in months:
        page = f"Deaths in {date(year, month, 1):%B} {year}"
        items = parse_deaths(_raw(page), year, month)
        log.info("%s: %d entries", page, len(items))
        rows += items
    qid = resolve_qids("en", sorted({r["title"] for r in rows}))
    out = []
    for r in rows:
        q = qid.get(r["title"])
        n = n_languages.get(q, 0) if q else 0
        if q and n >= min_languages:
            out.append({**r, "qid": q, "n_languages": n})
    for r in out:
        r["announcement"] = announcement_proxy(r["title"], r["date"])
    return out


# ---------------------------------------------------------------- GT2 earthquakes

def usgs_quakes(start: datetime, end: datetime, min_mag: float) -> list[dict]:
    r = _get(USGS, {"format": "geojson", "eventtype": "earthquake", "minmagnitude": min_mag,
                    "starttime": f"{start:%Y-%m-%dT%H:%M:%S}", "endtime": f"{end:%Y-%m-%dT%H:%M:%S}",
                    "orderby": "time-asc"})
    out = []
    for f in r.json()["features"]:
        p, g = f["properties"], f["geometry"]["coordinates"]
        out.append({"usgs_id": f["id"], "mag": p["mag"], "place": p["place"] or "",
                    "origin": datetime.fromtimestamp(p["time"] / 1000, tz=timezone.utc).replace(tzinfo=None),
                    "lon": g[0], "lat": g[1]})
    return out


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
            log.warning("sparql failed (%s), retry", e)
            time.sleep(5 * (attempt + 1))
    return []


def wikidata_quakes(start: date, end: date) -> list[dict]:
    """Earthquake items with a point in time in [start, end], with coordinates, magnitude and country."""
    q = f"""SELECT ?item ?t ?coord ?mag ?country WHERE {{
        ?item wdt:P31/wdt:P279* wd:Q7944 ; wdt:P585 ?t .
        FILTER(?t >= "{start}T00:00:00Z"^^xsd:dateTime && ?t <= "{end}T23:59:59Z"^^xsd:dateTime)
        OPTIONAL {{ ?item wdt:P625 ?coord }} OPTIONAL {{ ?item wdt:P2528 ?mag }} OPTIONAL {{ ?item wdt:P17 ?country }}
    }}"""
    out = {}
    for b in _sparql(q):
        qid = int(b["item"]["value"].rsplit("/Q", 1)[1])
        coord = b.get("coord", {}).get("value", "")
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", coord)
        out.setdefault(qid, {"qid": qid, "date": b["t"]["value"][:10],
                             "lon": float(m.group(1)) if m else None, "lat": float(m.group(2)) if m else None,
                             "mag": float(b["mag"]["value"]) if "mag" in b else None, "countries": set()})
        if "country" in b:
            out[qid]["countries"].add(int(b["country"]["value"].rsplit("/Q", 1)[1]))
    return list(out.values())


def first_sitelink_created(qid: int, langs: list[str]) -> datetime | None:
    """Earliest creation time among the item's sitelinked articles in our languages."""
    sites = "|".join(l.replace("-", "_") + "wiki" for l in langs)
    r = _get("https://www.wikidata.org/w/api.php", {"action": "wbgetentities", "ids": f"Q{qid}", "props": "sitelinks",
                                                   "sitefilter": sites, "format": "json"})
    links = r.json()["entities"][f"Q{qid}"].get("sitelinks", {})
    times = []
    for site, v in links.items():
        lang = site[:-4].replace("_", "-")
        rr = _get(f"https://{lang}.wikipedia.org/w/api.php", {"action": "query", "prop": "revisions",
                  "titles": v["title"], "rvdir": "newer", "rvlimit": 1, "rvprop": "timestamp", "format": "json",
                  "formatversion": 2})
        p = rr.json().get("query", {}).get("pages", [{}])[0]
        if p.get("revisions"):
            times.append(datetime.fromisoformat(p["revisions"][0]["timestamp"].replace("Z", "")))
    return min(times) if times else None


def _km(a_lat, a_lon, b_lat, b_lon) -> float:
    if None in (a_lat, a_lon, b_lat, b_lon):
        return float("inf")
    p = math.pi / 180
    h = (math.sin((b_lat - a_lat) * p / 2) ** 2
         + math.cos(a_lat * p) * math.cos(b_lat * p) * math.sin((b_lon - a_lon) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(h))


def place_parts(place: str) -> tuple[str | None, str]:
    """'45 km SW of Ambon, Indonesia' -> ('Ambon', 'Indonesia'); 'Kermadec Islands region' -> (None, ...)."""
    tail = re.sub(r"^.*?\bof\s+", "", place) if " of " in place else place
    if "," in tail:
        loc, region = tail.rsplit(",", 1)
        return loc.strip(), region.strip()
    return None, tail.strip()


US_STATES = {"Alaska", "California", "Hawaii", "Oregon", "Washington", "Nevada", "Idaho", "Montana", "Wyoming",
             "Utah", "Texas", "Oklahoma", "Puerto Rico"}


def quakes(start: datetime, end: datetime, langs: list[str]) -> list[dict]:
    raw = usgs_quakes(start, end, 6.0)
    wd = wikidata_quakes(start.date() - timedelta(days=1), end.date() + timedelta(days=2))
    names = set()
    for q in raw:
        loc, region = place_parts(q["place"])
        q["locality"], q["region"] = loc, region
        names |= {n for n in (loc, region) if n}
    resolved = resolve_qids("en", sorted(names))
    out = []
    for q in raw:
        o = q["origin"]
        cands = [w for w in wd if o.date() - timedelta(days=1) <= date.fromisoformat(w["date"]) <= o.date() + timedelta(days=2)]
        cands.sort(key=lambda w: (_km(q["lat"], q["lon"], w["lat"], w["lon"]),
                                  abs((w["mag"] or 0) - q["mag"]) if w["mag"] else 9))
        article, created = None, None
        for w in cands[:3]:
            if _km(q["lat"], q["lon"], w["lat"], w["lon"]) > 500 and w["lat"] is not None:
                continue
            c = first_sitelink_created(w["qid"], langs)
            if c and c <= o + timedelta(hours=48):
                article, created = w, c
                break
        targets_b = [resolved[n] for n in (q["locality"], q["region"]) if n and n in resolved]
        out.append({**q, "article_qid": article["qid"] if article else None, "article_created": created,
                    "article_countries": sorted(article["countries"]) if article else [],
                    "place_qids": targets_b,
                    "region_is_us_state": q["region"] in US_STATES})
    return out


# ---------------------------------------------------------------- GT3 matches

_BOX_START = re.compile(r"\{\{\s*(?:#invoke:\s*football box\s*\|\s*main|Football box)", re.I)


def _boxes(wikitext: str) -> list[dict]:
    """Fields of every football box ({{#invoke:football box|main ...}} or {{Football box ...}})."""
    out, cur = [], None
    for line in wikitext.splitlines():
        if _BOX_START.search(line):
            cur = {}
            out.append(cur)
            continue
        if cur is None:
            continue
        if line.strip().startswith("}}") or "<section end" in line:
            cur = None
            continue
        m = re.match(r"\|\s*(\w+)\s*=\s*(.*)$", line)
        if m:
            cur[m.group(1).lower()] = m.group(2).strip()
    return out


def _expand_links(text: str) -> list[str]:
    r = _get(EN_API, {"action": "expandtemplates", "text": text, "prop": "wikitext", "format": "json"})
    expanded = r.json()["expandtemplates"]["wikitext"]
    return [m.group(1).strip() for m in re.finditer(r"\[\[([^\[\]|#]+)(?:\|[^\]]*)?\]\]", expanded)
            if not m.group(1).lower().startswith(("file:", "image:"))]


def kickoff_utc(date_field: str, time_field: str) -> datetime | None:
    """{{Start date|2026|7|18}} + '5:00&nbsp;p.m. [[UTC−04:00|UTC−4]]' -> 2026-07-18 21:00 UTC."""
    d = re.search(r"(\d{4})\|(\d{1,2})\|(\d{1,2})", date_field)
    tf = time_field.replace("&nbsp;", " ")
    t = re.search(r"(\d{1,2}):(\d{2})\s*([ap])?\.?\s*m?", tf, re.I)
    off = re.search(r"UTC\s*([+−-])\s*(\d{1,2})(?::(\d{2}))?", tf)
    if not (d and t and off):
        return None
    hour = int(t.group(1)) % 12 + (12 if (t.group(3) or "").lower() == "p" else 0) if t.group(3) else int(t.group(1))
    local = datetime(int(d.group(1)), int(d.group(2)), int(d.group(3)), hour, int(t.group(2)))
    sign = -1 if off.group(1) in "−-" else 1
    return local - sign * timedelta(hours=int(off.group(2)), minutes=int(off.group(3) or 0))


def football_matches(page: str) -> list[dict]:
    out = []
    for f in _boxes(_raw(page)):
        ko = kickoff_utc(f.get("date", ""), f.get("time", ""))
        teams = []
        for side in ("team1", "team2"):
            links = [l for l in _expand_links(f.get(side, "")) if "national" in l.lower() or " team" in l.lower()]
            if links:
                teams.append(links[0])
        out.append({"page": page, "kickoff": ko, "teams": teams, "time_field": f.get("time", "")[:80],
                    "date_field": f.get("date", "")[:40],
                    "match_article": page if page.endswith(" final") else None})
    return out


def matches(pages: list[str]) -> list[dict]:
    rows = []
    for p in pages:
        rows += football_matches(p)
    titles = sorted({t for r in rows for t in r["teams"]} | {r["match_article"] for r in rows if r["match_article"]})
    q = resolve_qids("en", titles) if titles else {}
    for r in rows:
        r["team_qids"] = [q[t] for t in r["teams"] if t in q]
        r["match_qid"] = q.get(r["match_article"]) if r["match_article"] else None
    return rows


def dump(obj) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False, indent=1)
