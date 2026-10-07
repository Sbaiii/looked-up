"""Turn raw dump files into retained hourly tables (D2, D4, D5 schema).

Both sources go through the same DuckDB finalisation so their output is identical:

* hourly dump (``pageviews-*.gz``)   -> one table for its hour
* pageview_complete (``*-user.bz2``) -> 24 tables, one per hour of the day

Rules come from :mod:`lookedup.parse` (title normalisation is a Python UDF; namespace
and main-page exclusions are tables built from the same :class:`ArticleFilter`).
"""

from __future__ import annotations

import bz2
import logging
import tempfile
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.compute as pc

from lookedup import db
from lookedup.parse import (
    INVALID_TITLES,
    ArticleFilter,
    normalize_title,
    parse_pvc_line,
    parse_pvc_project,
)
from lookedup.settings import MIN_VIEWS

log = logging.getLogger(__name__)

SCHEMA = pa.schema([
    ("ts_hour_start", pa.timestamp("us")),  # naive, UTC by convention
    ("lang", pa.string()),
    ("title", pa.string()),
    ("views_desktop", pa.int32()),
    ("views_mobile", pa.int32()),
])


def _connect(langs: Iterable[str], filt: ArticleFilter) -> duckdb.DuckDBPyConnection:
    con = db.connect()
    con.create_function("norm_title", normalize_title, ["VARCHAR"], "VARCHAR", side_effects=False)
    langs = sorted(set(langs))
    con.execute("CREATE TEMP TABLE langs(lang VARCHAR)")
    con.executemany("INSERT INTO langs VALUES (?)", [(l,) for l in langs])
    con.execute("CREATE TEMP TABLE ns(lang VARCHAR, prefix VARCHAR)")
    con.executemany("INSERT INTO ns VALUES (?, ?)",
                    [(l, p) for l in langs for p in sorted(filt.namespaces_for(l))])
    con.execute("CREATE TEMP TABLE excluded(lang VARCHAR, title VARCHAR)")
    con.executemany("INSERT INTO excluded VALUES (?, ?)",
                    [(l, t) for l in langs for t in sorted(filt.excluded_titles(l) | INVALID_TITLES)])
    return con


# `staged` must provide (ts_hour_start TIMESTAMP, lang, mobile BOOLEAN, title_raw, views).
_FINALISE = """
WITH norm AS (
    SELECT ts_hour_start, lang, mobile, views,
           CASE WHEN contains(title_raw, '%') OR contains(title_raw, ' ')
                THEN norm_title(title_raw) ELSE title_raw END AS title
    FROM staged
),
art AS (
    SELECT n.* FROM norm n
    WHERE NOT EXISTS (SELECT 1 FROM excluded e WHERE e.lang = n.lang AND e.title = n.title)
      AND NOT EXISTS (
          SELECT 1 FROM ns
          WHERE ns.lang = n.lang
            AND ns.prefix = lower(trim(replace(regexp_extract(n.title, '^([^:]+):', 1), '_', ' ')))
      )
)
SELECT ts_hour_start, lang, title,
       coalesce(sum(views) FILTER (WHERE NOT mobile), 0)::INTEGER AS views_desktop,
       coalesce(sum(views) FILTER (WHERE mobile), 0)::INTEGER AS views_mobile
FROM art
GROUP BY ALL
HAVING views_desktop + views_mobile >= {min_views}
ORDER BY ts_hour_start, lang, title
"""


def _sql_str(path: Path) -> str:
    """Quote a filesystem path as a SQL string literal."""
    return "'" + str(path).replace("'", "''") + "'"


def _to_table(rel: duckdb.DuckDBPyRelation) -> pa.Table:
    fetch = getattr(rel, "to_arrow_table", None) or rel.fetch_arrow_table  # renamed in DuckDB 1.4
    return fetch().cast(SCHEMA)


def hourly_dump_to_table(path: Path, ts_hour_start: datetime, langs: Iterable[str],
                         filt: ArticleFilter, min_views: int = MIN_VIEWS) -> pa.Table:
    """Process one hourly dump (gzip or plain text) into the retained hourly table."""
    con = _connect(langs, filt)
    con.execute(f"""
        CREATE TEMP VIEW staged AS
        SELECT TIMESTAMP '{ts_hour_start:%Y-%m-%d %H:00:00}' AS ts_hour_start,
               split_part(project, '.', 1) AS lang,
               project LIKE '%.m' AS mobile,
               title AS title_raw, views
        FROM read_csv({_sql_str(path)}, delim=' ', header=false, quote='', escape='', auto_detect=false,
                      columns={{'project':'VARCHAR','title':'VARCHAR','views':'BIGINT','bytes':'BIGINT'}},
                      ignore_errors=true)
        WHERE project IN (SELECT lang FROM langs UNION ALL SELECT lang || '.m' FROM langs)
          AND title IS NOT NULL AND views IS NOT NULL
    """)
    return _to_table(con.sql(_FINALISE.format(min_views=min_views)))


def _pvc_to_tsv(path: Path, langs: set[str], out: Path) -> int:
    """Stream a pageview_complete file (bz2 or text) into a small TSV of our languages."""
    opener = bz2.open if path.suffix == ".bz2" else open
    n = 0
    with opener(path, "rt", encoding="utf-8", errors="replace") as f, open(out, "w", encoding="utf-8") as w:
        for line in f:
            dot = line.find(".")
            if dot < 0 or line[:dot] not in langs:  # cheap pre-filter on the language code
                continue
            parsed = parse_pvc_line(line)
            if not parsed:
                continue
            wiki, title, access, hourly = parsed
            pa_ = parse_pvc_project(wiki, access)
            if not pa_ or "\t" in title:
                continue
            w.write(f"{pa_[0]}\t{int(pa_[1])}\t{title}\t{hourly}\n")
            n += 1
    return n


def pageview_complete_to_tables(path: Path, day: date, langs: Iterable[str], filt: ArticleFilter,
                                min_views: int = MIN_VIEWS) -> dict[datetime, pa.Table]:
    """Process one pageview_complete day into 24 retained hourly tables (keyed by hour start)."""
    langs = set(langs)
    con = _connect(langs, filt)
    with tempfile.TemporaryDirectory() as tmp:
        tsv = Path(tmp) / "pvc.tsv"
        n = _pvc_to_tsv(path, langs, tsv)
        log.info("pageview_complete %s: %d lines for %d languages", day, n, len(langs))
        con.execute(f"""
            CREATE TEMP TABLE staged AS
            WITH src AS (
                SELECT * FROM read_csv({_sql_str(tsv)}, delim='\t', header=false, quote='', escape='',
                    auto_detect=false, columns={{'lang':'VARCHAR','mobile':'INTEGER','title_raw':'VARCHAR','hourly':'VARCHAR'}})
            ),
            cells AS (SELECT lang, mobile, title_raw, unnest(regexp_extract_all(hourly, '[A-X][0-9]+')) AS cell FROM src)
            SELECT TIMESTAMP '{day:%Y-%m-%d} 00:00:00' + to_hours(ascii(cell[1]) - 65) AS ts_hour_start,
                   lang, mobile = 1 AS mobile, title_raw, cell[2:]::BIGINT AS views
            FROM cells
        """)
        full = _to_table(con.sql(_FINALISE.format(min_views=min_views)))
    start = datetime(day.year, day.month, day.day)
    tables = {}
    for h in range(24):
        ts = start + timedelta(hours=h)
        mask = pc.equal(full["ts_hour_start"], pa.scalar(ts, pa.timestamp("us")))
        tables[ts] = full.filter(mask)
    return tables
