from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

import pyarrow as pa

from conftest import HOURLY_SAMPLE, LANGS, PVC_SAMPLE
from lookedup.parse import keep_row, normalize_title, parse_dump_line, parse_project
from lookedup.transform import SCHEMA, hourly_dump_to_table, pageview_complete_to_tables

HOUR = datetime(2026, 9, 13, 14)


def _rows(table: pa.Table) -> list[tuple]:
    return sorted(zip(*(table[c].to_pylist() for c in table.column_names)))


def test_hourly_schema_and_rules(article_filter):
    t = hourly_dump_to_table(HOURLY_SAMPLE, HOUR, LANGS, article_filter)
    assert t.schema == SCHEMA
    assert t.num_rows > 100
    assert set(t["ts_hour_start"].to_pylist()) == {HOUR}
    assert set(t["lang"].to_pylist()) <= set(LANGS)
    for lang, title, d, m in zip(*(t[c].to_pylist() for c in ("lang", "title", "views_desktop", "views_mobile"))):
        assert article_filter.is_article(lang, title), (lang, title)
        assert keep_row(d, m)
    # desktop and mobile are stored separately, never pre-summed (D2)
    assert any(d > 0 and m > 0 for d, m in zip(t["views_desktop"].to_pylist(), t["views_mobile"].to_pylist()))


def test_hourly_sql_matches_python_reference(article_filter):
    """The DuckDB path applies exactly the rules defined in lookedup.parse."""
    agg: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for line in HOURLY_SAMPLE.read_text(encoding="utf-8").splitlines():
        parsed = parse_dump_line(line)
        if not parsed:
            continue
        project, raw_title, views = parsed
        pm = parse_project(project)
        if not pm or pm[0] not in LANGS:
            continue
        lang, mobile = pm
        title = normalize_title(raw_title)
        if article_filter.is_article(lang, title):
            agg[(lang, title)][int(mobile)] += views
    expected = sorted((HOUR, l, t, d, m) for (l, t), (d, m) in agg.items() if keep_row(d, m))
    got = _rows(hourly_dump_to_table(HOURLY_SAMPLE, HOUR, LANGS, article_filter))
    assert got == expected


def test_language_subset_is_respected(article_filter):
    t = hourly_dump_to_table(HOURLY_SAMPLE, HOUR, ["fr"], article_filter)
    assert set(t["lang"].to_pylist()) == {"fr"}


def test_pageview_complete_matches_hourly_dump(article_filter):
    """Backfill (pageview_complete) and live (hourly dump) produce identical rows (D7)."""
    tables = pageview_complete_to_tables(PVC_SAMPLE, date(2026, 9, 13), LANGS, article_filter)
    assert sorted(tables) == [datetime(2026, 9, 13, h) for h in range(24)]
    assert all(tb.schema == SCHEMA for tb in tables.values())
    hourly = hourly_dump_to_table(HOURLY_SAMPLE, HOUR, LANGS, article_filter)
    assert _rows(tables[HOUR]) == _rows(hourly)
