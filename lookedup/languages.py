"""D3: the language set, ranked by HUMAN article views over 7 full days.

Pipeline (``python -m lookedup.cli languages``):

1. Stream 7 ``pageview_complete`` user files into per-day (lang, title, desktop, mobile)
   Parquet aggregates (all Wikipedias).
2. Candidates = top ``CANDIDATES`` Wikipedias by raw views; fetch their namespaces and
   main page from each wiki's siteinfo API -> ``config/namespaces.json``.
3. Human article views = views on titles that are articles (no namespace prefix, not
   the main page, not ``-``) minus titles that look automated: > 1,000 views over the
   7 days with < 5 % mobile.
4. Rank, attach names (sitematrix) and speaker counts (Wikidata P1098), write
   ``config/languages.yml``. ``active`` = first ``top_n`` entries; raise ``top_n`` to extend.
"""

from __future__ import annotations

import bz2
import json
import logging
import tempfile
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import requests
import yaml

from lookedup import db
from lookedup.dumps import download, pvc_url, session
from lookedup.parse import ArticleFilter, parse_pvc_line, parse_pvc_project
from lookedup.settings import LANGUAGES_FILE, NAMESPACES_FILE, RAW_DIR

log = logging.getLogger(__name__)

CANDIDATES = 60
AUTOMATION_MIN_VIEWS = 1000
AUTOMATION_MAX_MOBILE_SHARE = 0.05


@dataclass(frozen=True)
class Language:
    code: str
    name_en: str | None
    name_native: str | None
    speakers: int | None
    rank: int


# ---------------------------------------------------------------- config I/O

def load_config(path: Path = LANGUAGES_FILE) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def active_languages(path: Path = LANGUAGES_FILE) -> list[Language]:
    """The languages ingested today: the first ``top_n`` entries of the ranking."""
    cfg = load_config(path)
    ranked = sorted(cfg["languages"], key=lambda x: x["rank"])
    return [Language(code=x["code"], name_en=x.get("name_en"), name_native=x.get("name_native"),
                     speakers=x.get("speakers"), rank=x["rank"]) for x in ranked[: cfg["top_n"]]]


def active_codes(path: Path = LANGUAGES_FILE) -> list[str]:
    return [l.code for l in active_languages(path)]


def article_filter(path: Path = NAMESPACES_FILE) -> ArticleFilter:
    """ArticleFilter built from config/namespaces.json."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return ArticleFilter(namespaces={l: v["namespaces"] for l, v in data.items()},
                         main_pages={l: v["main_page"] for l, v in data.items()})


# ---------------------------------------------------------------- wiki metadata

def _get_json(url: str, params: dict, retries: int = 5, **kw) -> dict:
    """GET with retries: metadata calls must not lose 30 minutes of aggregation to one dropped connection."""
    for attempt in range(retries):
        try:
            r = session().get(url, params=params, timeout=60, **kw)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            log.warning("%s failed (%s), retry %d", url, e, attempt + 1)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("unreachable")


def fetch_siteinfo(lang: str) -> dict:
    """Main page title and every non-article namespace name/alias of one Wikipedia."""
    q = _get_json(f"https://{lang}.wikipedia.org/w/api.php", {
        "action": "query", "meta": "siteinfo", "siprop": "general|namespaces|namespacealiases",
        "format": "json", "formatversion": 2})["query"]
    names = set()
    for ns in q["namespaces"].values():
        if ns["id"] != 0:
            for key in ("name", "canonical"):
                if ns.get(key):
                    names.add(ns[key].lower())
    for alias in q.get("namespacealiases", []):
        if alias["id"] != 0:
            names.add(alias["alias"].lower())
    return {"main_page": q["general"]["mainpage"].replace(" ", "_"), "namespaces": sorted(names)}


def fetch_names() -> dict[str, tuple[str | None, str | None]]:
    """lang code -> (English name, native name) from the sitematrix API."""
    data = _get_json("https://meta.wikimedia.org/w/api.php", {
        "action": "sitematrix", "smtype": "language", "smlangprop": "code|name|localname",
        "format": "json", "uselang": "en"})
    out = {}
    for k, v in data["sitematrix"].items():
        if k.isdigit():
            out[v["code"]] = (v.get("localname"), v.get("name"))
    return out


def fetch_speakers(codes: list[str]) -> dict[str, int]:
    """Approximate speaker counts: max P1098 of the item whose P424 (Wikimedia code) matches."""
    values = " ".join(f'"{c}"' for c in codes)
    query = f"""
        SELECT ?code (MAX(?n) AS ?speakers) WHERE {{
          VALUES ?code {{ {values} }}
          ?item wdt:P424 ?code ; wdt:P1098 ?n .
        }} GROUP BY ?code"""
    try:
        r = session().get("https://query.wikidata.org/sparql", params={"query": query, "format": "json"},
                          headers={"Accept": "application/sparql-results+json"}, timeout=60)
        r.raise_for_status()
    except Exception as e:  # metadata only: never block the language list on it
        log.warning("speaker counts unavailable: %s", e)
        return {}
    return {b["code"]["value"]: int(float(b["speakers"]["value"]))
            for b in r.json()["results"]["bindings"]}


# ---------------------------------------------------------------- ranking

def _day_aggregate(path: Path, out: Path) -> None:
    """One pageview_complete day -> Parquet of (lang, title, desktop, mobile) for all Wikipedias."""
    with tempfile.TemporaryDirectory() as tmp:
        tsv = Path(tmp) / "day.tsv"
        with bz2.open(path, "rt", encoding="utf-8", errors="replace") as f, open(tsv, "w") as w:
            for line in f:
                if ".wikipedia " not in line[:40]:
                    continue
                parsed = parse_pvc_line(line)
                if not parsed:
                    continue
                wiki, title, access, _ = parsed
                pa_ = parse_pvc_project(wiki, access)
                daily = line.rstrip("\n").split(" ")[-2]
                if pa_ and "\t" not in title and daily.isdigit():
                    w.write(f"{pa_[0]}\t{title}\t{int(pa_[1])}\t{daily}\n")
        db.connect().sql(f"""
            COPY (
                SELECT lang, title,
                       sum(v) FILTER (WHERE m = 0)::BIGINT AS desktop,
                       sum(v) FILTER (WHERE m = 1)::BIGINT AS mobile
                FROM read_csv('{tsv}', delim='\t', header=false, quote='', escape='', auto_detect=false,
                     columns={{'lang':'VARCHAR','title':'VARCHAR','m':'INTEGER','v':'BIGINT'}})
                GROUP BY ALL
            ) TO '{out}' (FORMAT parquet, COMPRESSION zstd)
        """)


def rank_languages(days: list[date], work_dir: Path | None = None, candidates: int = CANDIDATES,
                   keep_raw: bool = True) -> list[dict]:
    """Rank Wikipedias by human article views over ``days`` (see module docstring)."""
    work = work_dir or RAW_DIR / "languages"
    work.mkdir(parents=True, exist_ok=True)
    day_files = []
    for d in days:
        out = work / f"agg-{d:%Y%m%d}.parquet"
        if not out.exists():
            raw = download(pvc_url(d), RAW_DIR / "pageview_complete" / pvc_url(d).rsplit("/", 1)[1])
            log.info("aggregating %s", raw.name)
            _day_aggregate(raw, out)
            if not keep_raw:
                raw.unlink()
        day_files.append(out)

    con = db.connect()
    files = ", ".join(f"'{p}'" for p in day_files)
    week = work / f"window-{days[0]:%Y%m%d}-{days[-1]:%Y%m%d}.parquet"
    if not week.exists():  # the expensive step (~30 min): cache it so re-runs are quick
        con.execute(f"""COPY (SELECT lang, title, sum(coalesce(desktop,0)) AS d, sum(coalesce(mobile,0)) AS m
                        FROM read_parquet([{files}]) GROUP BY ALL) TO '{week}' (FORMAT parquet, COMPRESSION zstd)""")
    con.execute(f"CREATE VIEW t AS SELECT * FROM read_parquet('{week}')")
    raw_rank = [r[0] for r in con.execute(
        "SELECT lang FROM t GROUP BY 1 ORDER BY sum(d + m) DESC").fetchall()]
    cand = raw_rank[:candidates]

    namespaces = {}
    for lang in cand:
        namespaces[lang] = fetch_siteinfo(lang)
    NAMESPACES_FILE.parent.mkdir(parents=True, exist_ok=True)
    NAMESPACES_FILE.write_text(json.dumps(namespaces, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                               encoding="utf-8")
    filt = article_filter(NAMESPACES_FILE)

    con.execute("CREATE TABLE ns(lang VARCHAR, prefix VARCHAR)")
    con.executemany("INSERT INTO ns VALUES (?, ?)", [(l, p) for l in cand for p in filt.namespaces_for(l)])
    con.execute("CREATE TABLE excl(lang VARCHAR, title VARCHAR)")
    con.executemany("INSERT INTO excl VALUES (?, ?)",
                    [(l, t) for l in cand for t in filt.excluded_titles(l) | {"-", ""}])
    con.execute("CREATE TABLE cand(lang VARCHAR)")
    con.executemany("INSERT INTO cand VALUES (?)", [(l,) for l in cand])
    rows = con.execute(f"""
        WITH c AS (
            SELECT t.*, NOT EXISTS (SELECT 1 FROM excl e WHERE e.lang = t.lang AND e.title = t.title)
                    AND NOT EXISTS (SELECT 1 FROM ns WHERE ns.lang = t.lang AND ns.prefix =
                        lower(trim(replace(regexp_extract(t.title, '^([^:]+):', 1), '_', ' ')))) AS is_article
            FROM t WHERE lang IN (SELECT lang FROM cand)
        ), f AS (
            SELECT *, is_article AND (d + m) > {AUTOMATION_MIN_VIEWS}
                      AND m < {AUTOMATION_MAX_MOBILE_SHARE} * (d + m) AS automated
            FROM c
        )
        SELECT lang,
               sum(d + m) AS raw_views,
               sum(d + m) FILTER (WHERE is_article AND NOT automated) AS human_views,
               sum(m) FILTER (WHERE is_article AND NOT automated) AS human_mobile,
               sum(d + m) FILTER (WHERE automated) AS automated_views,
               sum(d + m) FILTER (WHERE NOT is_article) AS non_article_views
        FROM f GROUP BY 1 ORDER BY human_views DESC
    """).fetchall()
    total_human = sum(r[2] or 0 for r in rows)
    out, cum = [], 0
    for i, (lang, raw_v, human, hm, auto_v, non_art) in enumerate(rows, 1):
        cum += human or 0
        out.append({
            "rank": i, "code": lang, "raw_views_7d": int(raw_v), "human_views_7d": int(human or 0),
            "mobile_share": round((hm or 0) / human, 3) if human else None,
            "automated_share": round((auto_v or 0) / raw_v, 3), "non_article_share": round((non_art or 0) / raw_v, 3),
            "cumulative_share_of_candidates": round(cum / total_human, 4),
            "raw_rank": raw_rank.index(lang) + 1,
        })
    return out


def write_config(ranking: list[dict], days: list[date], top_n: int = 30, path: Path = LANGUAGES_FILE) -> None:
    """Write config/languages.yml with names and speaker counts attached."""
    names = fetch_names()
    speakers = fetch_speakers([r["code"] for r in ranking])
    langs = []
    for r in ranking:
        en, native = names.get(r["code"], (None, None))
        langs.append({"code": r["code"], "rank": r["rank"], "name_en": en, "name_native": native,
                      "speakers": speakers.get(r["code"]), **{k: v for k, v in r.items() if k not in ("code", "rank")}})
    doc = {
        "top_n": top_n,
        "method": ("Ranked by human article views over 7 full days of pageview_complete: excludes main page, "
                   "namespace-prefixed titles (localised, from siteinfo), '-', and titles with >1,000 views and "
                   "<5% mobile. Ingestion uses the first top_n entries; raise top_n to extend."),
        "window": {"from": f"{days[0]:%Y-%m-%d}", "to": f"{days[-1]:%Y-%m-%d}"},
        "languages": langs,
    }
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")


def last_full_days(n: int = 7, today: date | None = None) -> list[date]:
    """The ``n`` most recent days whose pageview_complete file should exist (ends yesterday)."""
    today = today or date.today()
    return [today - timedelta(days=i) for i in range(n, 0, -1)]
