"""Ground truth from Wikipedia's Portal:Current events (prereg §3).

For every day, fetch ``Portal:Current_events/<YYYY>_<Month>_<D>`` as wikitext, split it into
entries (one per bullet), keep the section heading as the portal's category, extract the
wikilinks of each bullet (and ``{{ill|title|lang|foreign title}}`` links to articles that only
exist in another language), and resolve each linked title to a Wikidata QID (redirects followed).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta

import requests

from lookedup.dumps import session

log = logging.getLogger(__name__)

_HEADING = re.compile(r"^'''([^']+)'''\s*$")
_BULLET = re.compile(r"^(\*+)\s*(.*)$")
_LINK = re.compile(r"\[\[([^\[\]|#]+)(?:#[^\[\]|]*)?(?:\|[^\[\]]*)?\]\]")
_ILL = re.compile(r"\{\{\s*ill\s*\|([^|}]+)\|([a-z-]+)\|([^|}]+)")
_SKIP_NS = ("file:", "image:", "category:", "wikt:", "portal:", "template:", ":")


@dataclass(frozen=True)
class Link:
    date: date
    section: str
    entry_index: int
    depth: int
    text: str
    lang: str      # wiki the title lives on: "en", or the language of an {{ill}} link
    title: str


def page_title(day: date) -> str:
    return f"Portal:Current_events/{day.year}_{day:%B}_{day.day}"


def parse_day(wikitext: str, day: date) -> list[Link]:
    """All (entry, link) pairs of one day's portal page."""
    out: list[Link] = []
    section = "Uncategorized"
    entry = 0
    for raw in wikitext.splitlines():
        line = raw.strip()
        h = _HEADING.match(line)
        if h:
            section = h.group(1).strip()
            continue
        b = _BULLET.match(line)
        if not b:
            continue
        entry += 1
        depth, body = len(b.group(1)), b.group(2)
        text = re.sub(r"\[https?://\S+ [^\]]*\]", "", body)
        text = _LINK.sub(lambda m: m.group(0).split("|")[-1].strip("[]"), text)[:300]
        seen = set()
        for m in _LINK.finditer(body):
            title = m.group(1).strip()
            if not title or title.lower().startswith(_SKIP_NS):
                continue
            key = ("en", title)
            if key not in seen:
                seen.add(key)
                out.append(Link(day, section, entry, depth, text, "en", title))
        for m in _ILL.finditer(body):
            lang, foreign = m.group(2).strip(), m.group(3).strip()
            key = (lang, foreign)
            if key not in seen:
                seen.add(key)
                out.append(Link(day, section, entry, depth, text, lang, foreign))
    return out


def fetch_day(day: date, retries: int = 5) -> str:
    for attempt in range(retries):
        try:
            r = session().get("https://en.wikipedia.org/w/index.php",
                              params={"title": page_title(day), "action": "raw"}, timeout=60)
            if r.status_code == 404:
                return ""
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            log.warning("fetch %s failed (%s), retry", day, e)
            time.sleep(3 * (attempt + 1))
    return ""


def resolve_qids(lang: str, titles: list[str], batch: int = 50) -> dict[str, int]:
    """title -> numeric QID on ``lang``.wikipedia, following redirects (missing pages are skipped)."""
    out: dict[str, int] = {}
    for i in range(0, len(titles), batch):
        chunk = titles[i:i + batch]
        for attempt in range(5):
            try:
                r = session().get(f"https://{lang}.wikipedia.org/w/api.php", params={
                    "action": "query", "titles": "|".join(chunk), "redirects": 1, "prop": "pageprops",
                    "ppprop": "wikibase_item", "format": "json", "formatversion": 2}, timeout=60)
                r.raise_for_status()
                q = r.json().get("query", {})
                break
            except (requests.RequestException, ValueError) as e:
                if attempt == 4:
                    raise
                log.warning("resolve failed (%s), retry", e)
                time.sleep(3 * (attempt + 1))
        # map every input title through normalisation and redirects to the final page
        alias = {t: t for t in chunk}
        for step in ("normalized", "redirects"):
            for n in q.get(step, []):
                for src, dst in list(alias.items()):
                    if dst == n["from"]:
                        alias[src] = n["to"]
        qid_of = {p["title"]: p.get("pageprops", {}).get("wikibase_item") for p in q.get("pages", [])}
        for src, final in alias.items():
            item = qid_of.get(final)
            if item and item.startswith("Q"):
                out[src] = int(item[1:])
        time.sleep(0.2)
    return out


def days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def build(start: date, end: date, sitelinks_path, claims_cache, out_path, cfg) -> dict:
    """Fetch, parse and resolve every day; mark major (date, QID) pairs; write Parquet."""
    import json

    import pyarrow as pa
    import pyarrow.parquet as pq

    from lookedup import db
    from lookedup.analytics.entities import fetch_claims, is_generic

    links: list[Link] = []
    for d in days(start, end):
        day_links = parse_day(fetch_day(d), d)
        links += day_links
        log.info("current events %s: %d links", d, len(day_links))
        time.sleep(0.2)
    qid: dict[tuple[str, str], int] = {}
    for lang in sorted({l.lang for l in links}):
        titles = sorted({l.title for l in links if l.lang == lang})
        for t, q in resolve_qids(lang, titles).items():
            qid[(lang, t)] = q
    qids = sorted(set(qid.values()))
    con = db.connect()
    n_lang = dict(con.execute(f"""select qid, count(distinct lang) from read_parquet('{sitelinks_path}')
                                  where qid in (select unnest(?::BIGINT[])) group by qid""", [qids]).fetchall())
    claims = fetch_claims(qids, claims_cache)
    generic = {q for q, cj in zip(claims["qid"].to_pylist(), claims["claims_json"].to_pylist())
               if is_generic(json.loads(cj), cfg)}
    min_langs = cfg.raw["evaluation"]["major_min_languages"]
    rows = []
    for l in links:
        q = qid.get((l.lang, l.title))
        n = n_lang.get(q, 0) if q else 0
        rows.append({"date": l.date, "section": l.section, "entry_index": l.entry_index, "depth": l.depth,
                     "text": l.text, "link_lang": l.lang, "link_title": l.title, "qid": q,
                     "n_languages": n, "is_generic": q in generic,
                     "is_major": q is not None and q not in generic and n >= min_langs})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), out_path)
    majors = {(r["date"], r["qid"]) for r in rows if r["is_major"]}
    return {"days": len(days(start, end)), "links": len(rows), "entries": len({(r["date"], r["entry_index"]) for r in rows}),
            "resolved": sum(r["qid"] is not None for r in rows), "major_pairs": len(majors)}
