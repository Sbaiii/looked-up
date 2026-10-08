"""D8: (lang, title) -> Wikidata QID mapping from ``wb_items_per_site``.

The 1.9 GB SQL dump is streamed line by line (mariadb-dump writes one tuple per
line); only sitelinks of the active languages are kept, written to Parquet in
batches, then sorted by (lang, title) with DuckDB (out of core). ``qid`` is the
numeric part (Q597 -> 597).
"""

from __future__ import annotations

import gzip
import io
import logging
import re
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from lookedup import db
from lookedup.dumps import download
from lookedup.settings import RAW_DIR, SITELINKS_DUMP

log = logging.getLogger(__name__)

# (ips_row_id, ips_item_id, 'ips_site_id', 'ips_site_page')
_TUPLE = re.compile(rb"\((\d+),(\d+),'((?:[^'\\]|\\.)*)','((?:[^'\\]|\\.)*)'\)")
_UNESCAPE = re.compile(rb"\\(.)")
SCHEMA = pa.schema([("lang", pa.string()), ("title", pa.string()), ("qid", pa.int32())])
BATCH = 1_000_000


def site_id(lang: str) -> str:
    """Wikipedia language code -> Wikidata site id (``zh-yue`` -> ``zh_yuewiki``)."""
    return lang.replace("-", "_") + "wiki"


def parse_sitelinks(lines, sites: dict[bytes, str]):
    """Yield (lang, title_with_underscores, qid) for rows whose site is in ``sites``."""
    for line in lines:
        if not (line.startswith(b"(") or line.startswith(b"INSERT INTO")):
            continue
        for _row, item, site, page in _TUPLE.findall(line):
            lang = sites.get(site)
            if lang is None:
                continue
            title = _UNESCAPE.sub(rb"\1", page).decode("utf-8", "replace").replace(" ", "_")
            yield lang, title, int(item)


def build_sitelinks(langs: list[str], out: Path, dump: Path | None = None) -> dict:
    """Stream the dump into ``out`` (sorted Parquet). Returns row counts per language."""
    dump = dump or download(SITELINKS_DUMP, RAW_DIR / "wikidata" / "wb_items_per_site.sql.gz")
    sites = {site_id(l).encode(): l for l in langs}
    counts: dict[str, int] = {}
    with tempfile.TemporaryDirectory() as tmp:
        unsorted = Path(tmp) / "unsorted.parquet"
        writer = pq.ParquetWriter(unsorted, SCHEMA, compression="zstd")
        cols: tuple[list, list, list] = ([], [], [])
        with gzip.open(dump, "rb") as f:
            for lang, title, qid in parse_sitelinks(io.BufferedReader(f, 1 << 24), sites):
                cols[0].append(lang)
                cols[1].append(title)
                cols[2].append(qid)
                counts[lang] = counts.get(lang, 0) + 1
                if len(cols[0]) >= BATCH:
                    writer.write_table(pa.table(list(cols), schema=SCHEMA))
                    cols = ([], [], [])
        if cols[0]:
            writer.write_table(pa.table(list(cols), schema=SCHEMA))
        writer.close()
        out.parent.mkdir(parents=True, exist_ok=True)
        con = db.connect()
        con.execute(f"SET temp_directory='{tmp}'")
        con.execute("SET memory_limit='1GB'")  # spill the sort to disk instead of holding it in RAM
        con.execute(f"""COPY (SELECT * FROM '{unsorted}' ORDER BY lang, title)
                        TO '{out}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 1000000)""")
    log.info("sitelinks: %d rows for %d languages -> %s (%d bytes)", sum(counts.values()), len(counts),
             out, out.stat().st_size)
    return counts


def join_coverage(hourly_files: list[str], sitelinks: str) -> list[tuple[str, int, int, float]]:
    """Per language: (lang, views, views matched to a QID, % matched) over the given hourly files."""
    files = ", ".join("'" + f.replace("'", "''") + "'" for f in hourly_files)
    rows = db.connect().sql(f"""
        WITH h AS (SELECT lang, title, views_desktop + views_mobile AS v FROM read_parquet([{files}]))
        SELECT h.lang, sum(v)::BIGINT AS views, sum(v) FILTER (WHERE s.qid IS NOT NULL)::BIGINT AS matched
        FROM h LEFT JOIN read_parquet('{sitelinks}') s USING (lang, title)
        GROUP BY 1 ORDER BY views DESC
    """).fetchall()
    return [(l, v, m or 0, round(100 * (m or 0) / v, 1)) for l, v, m in rows]
