"""Q4: entity unification through Wikidata.

1. wbgetentities: one QID -> title in every language.
2. wb_items_per_site SQL dump: size, structure, first rows (8 MB range read).
3. --full: stream the whole dump, parse INSERT tuples, write a Wikipedia-only
   (site, title) -> QID Parquet and report row counts.

Usage: .venv/bin/python spike/q4_wikidata.py [--full]
"""

from __future__ import annotations

import gzip
import io
import json
import re
import sys
import time
import zlib

import pyarrow as pa
import pyarrow.parquet as pq

from common import DERIVED, RAW, download, session

WD_API = "https://www.wikidata.org/w/api.php"
DUMP = "https://dumps.wikimedia.org/wikidatawiki/latest/wikidatawiki-latest-wb_items_per_site.sql.gz"
# (ips_row_id, ips_item_id, 'ips_site_id', 'ips_site_page')
TUPLE = re.compile(rb"\((\d+),(\d+),'((?:[^'\\]|\\.)*)','((?:[^'\\]|\\.)*)'\)")


def unescape(b: bytes) -> str:
    return re.sub(rb"\\(.)", rb"\1", b).decode("utf-8", "replace")


def api_demo() -> dict:
    r = session.get(WD_API, params={"action": "wbgetentities", "sites": "enwiki", "titles": "Lisbon",
                                    "props": "sitelinks", "format": "json"}, timeout=30)
    ent = next(iter(r.json()["entities"].values()))
    links = ent["sitelinks"]
    wp = {k: v["title"] for k, v in links.items()
          if k.endswith("wiki") and k not in ("commonswiki", "specieswiki", "metawiki", "wikidatawiki", "mediawikiwiki")}
    return {"qid": ent["id"], "sitelinks_total": len(links), "wikipedia_sitelinks": len(wp),
            "sample": {k: wp[k] for k in ["enwiki", "ptwiki", "frwiki", "jawiki", "arwiki", "ruwiki", "zhwiki", "hiwiki"] if k in wp}}


def dump_head() -> dict:
    head = session.head(DUMP, timeout=30, allow_redirects=True)
    r = session.get(DUMP, headers={"Range": "bytes=0-8388607"}, timeout=120)
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    text = d.decompress(r.content)
    create = re.search(rb"CREATE TABLE `wb_items_per_site` \(.*?\) ENGINE[^;]*;", text, re.S)
    tuples = TUPLE.findall(text)
    sites = {}
    for _, _, s, _ in tuples:
        sites[s] = sites.get(s, 0) + 1
    return {
        "gz_bytes": int(head.headers.get("Content-Length", 0)),
        "last_modified": head.headers.get("Last-Modified"),
        "range_read_bytes": len(r.content),
        "uncompressed_sample_bytes": len(text),
        "create_table": create.group(0).decode() if create else None,
        "sample_rows": [(int(a), int(b), unescape(c), unescape(dd)) for a, b, c, dd in tuples[:8]],
        "sample_tuples": len(tuples),
        "est_total_rows": int(len(tuples) * int(head.headers.get("Content-Length", 0)) / len(r.content)),
        "sample_distinct_sites": len(sites),
    }


def full(langs: set[str]) -> dict:
    """Download (if needed) and stream-parse the whole dump."""
    dest = RAW / "wikidata" / "wb_items_per_site.sql.gz"
    _, dl_s = download(DUMP, dest)
    t0 = time.perf_counter()
    total = wiki_rows = 0
    sites: dict[str, int] = {}
    batch_site, batch_title, batch_qid = [], [], []
    writer = None
    out = DERIVED / "sitelinks_wikipedia_top50.parquet"
    schema = pa.schema([("site", pa.string()), ("title", pa.string()), ("qid", pa.int32())])
    with gzip.open(dest, "rb") as f:
        for line in io.BufferedReader(f, 1 << 24):
            # mariadb-dump 10.11 writes one "(...)," tuple per line after "INSERT INTO ... VALUES"
            if not (line.startswith(b"(") or line.startswith(b"INSERT INTO")):
                continue
            for _, item, site, page in TUPLE.findall(line):
                total += 1
                s = site.decode()
                sites[s] = sites.get(s, 0) + 1
                if s.endswith("wiki") and s[:-4].replace("_", "-") in langs:
                    wiki_rows += 1
                    batch_site.append(s)
                    batch_title.append(unescape(page).replace(" ", "_"))
                    batch_qid.append(int(item))
            if len(batch_qid) > 2_000_000:
                tbl = pa.table([batch_site, batch_title, batch_qid], schema=schema)
                writer = writer or pq.ParquetWriter(out, schema, compression="zstd")
                writer.write_table(tbl)
                batch_site, batch_title, batch_qid = [], [], []
    if batch_qid:
        writer = writer or pq.ParquetWriter(out, schema, compression="zstd")
        writer.write_table(pa.table([batch_site, batch_title, batch_qid], schema=schema))
    if writer:
        writer.close()
    wikipedias = {s: n for s, n in sites.items() if s.endswith("wiki")
                  and s not in ("commonswiki", "specieswiki", "metawiki", "wikidatawiki", "mediawikiwiki",
                                "sourceswiki", "wikimaniawiki", "outreachwiki", "incubatorwiki", "wikifunctionswiki")}
    return {"download_s": round(dl_s, 1), "parse_s": round(time.perf_counter() - t0, 1),
            "total_rows": total, "distinct_sites": len(sites), "wikipedia_sites": len(wikipedias),
            "top50_rows": wiki_rows, "top50_parquet_bytes": out.stat().st_size,
            "top_sites": sorted(sites.items(), key=lambda x: -x[1])[:15]}


def main() -> None:
    res = {"api": api_demo(), "dump": dump_head()}
    print(json.dumps(res, indent=2, ensure_ascii=False))
    if "--full" in sys.argv:
        q1 = json.loads((DERIVED / "q1_summary.json").read_text())
        langs = {l for l, _, _ in q1["top50_langs"]}
        res["full"] = full(langs)
        print(json.dumps(res["full"], indent=2))
    (DERIVED / "q4_wikidata.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
