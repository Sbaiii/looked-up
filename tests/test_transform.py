from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

import pyarrow as pa
from conftest import HOURLY_SAMPLE, LANGS, PVC_SAMPLE

from lookedup.parse import keep_row, normalize_title, parse_dump_line, parse_project
from lookedup.transform import SCHEMA, hourly_dump_to_table, pageview_complete_to_tables

HOUR = datetime(2026, 9, 13, 14)


def _rows(table: pa.Table) -> list[tuple]:
    return sorted(zip(*(table[c].to_pylist() for c in table.column_names), strict=True))


def test_hourly_schema_and_rules(article_filter):
    t = hourly_dump_to_table(HOURLY_SAMPLE, HOUR, LANGS, article_filter)
    assert t.schema == SCHEMA
    assert t.num_rows > 100
    assert set(t["ts_hour_start"].to_pylist()) == {HOUR}
    assert set(t["lang"].to_pylist()) <= set(LANGS)
    for lang, title, d, m in zip(*(t[c].to_pylist() for c in ("lang", "title", "views_desktop", "views_mobile")), strict=True):
        assert article_filter.is_article(lang, title), (lang, title)
        assert keep_row(d, m)
    # desktop and mobile are stored separately, never pre-summed (D2)
    assert any(d > 0 and m > 0 for d, m in zip(t["views_desktop"].to_pylist(), t["views_mobile"].to_pylist(), strict=True))


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


def test_pvc_prefilter_skips_other_wikis_and_bad_lines(tmp_path):
    from lookedup.transform import _pvc_to_tsv

    src = tmp_path / "day.txt"
    src.write_text("en.wikipedia Lisbon 597 desktop 30 A30\n"
                   "en.wikipedia broken line\n"
                   "xx.wikipedia Lisbon 597 desktop 30 A30\n"
                   "en.wiktionary Lisbon 1 desktop 3 A3\n"
                   "noline\n")
    out = tmp_path / "out.tsv"
    assert _pvc_to_tsv(src, {"en"}, out) == 1
    assert out.read_text().split("\t")[:3] == ["en", "0", "Lisbon"]


def test_title_spellings_merge(tmp_path, article_filter):
    src = tmp_path / "dump"
    src.write_text("en Caf%C3%A9_Society 3 0\nen Café_Society 2 0\nen.m Café_Society 4 0\nen New%20York 5 0\n")
    rows = _rows(hourly_dump_to_table(src, HOUR, ["en"], article_filter))
    assert rows == [(HOUR, "en", "Café_Society", 5, 4), (HOUR, "en", "New_York", 5, 0)]


def test_non_articles_are_dropped(tmp_path, article_filter):
    src = tmp_path / "dump"
    src.write_text("en Main_Page 900 0\nen Special:Search 900 0\nen.d Lisbon 900 0\nen Talk:Lisbon 900 0\n"
                   "en - 900 0\nen Lisbon 900 0\n")
    assert [r[2] for r in _rows(hourly_dump_to_table(src, HOUR, ["en"], article_filter))] == ["Lisbon"]


def test_custom_view_floor(tmp_path, article_filter):
    src = tmp_path / "dump"
    src.write_text("en A 3 0\nen B 1 0\n")
    assert [r[2] for r in _rows(hourly_dump_to_table(src, HOUR, ["en"], article_filter))] == []
    assert [r[2] for r in _rows(hourly_dump_to_table(src, HOUR, ["en"], article_filter, min_views=2))] == ["A"]


def test_path_with_a_quote(tmp_path, article_filter):
    src = tmp_path / "o'clock dump"
    src.write_text("en Lisbon 9 0\n")
    assert _rows(hourly_dump_to_table(src, HOUR, ["en"], article_filter)) == [(HOUR, "en", "Lisbon", 9, 0)]


def test_plain_text_pageview_complete(tmp_path, article_filter):
    src = tmp_path / "day.txt"
    src.write_text("en.wikipedia Lisbon 597 desktop 12 A5O7\nen.wikipedia Lisbon 597 mobile-web 9 A4\n")
    tables = pageview_complete_to_tables(src, date(2026, 9, 13), ["en"], article_filter)
    assert _rows(tables[datetime(2026, 9, 13, 0)]) == [(datetime(2026, 9, 13, 0), "en", "Lisbon", 5, 4)]
    assert _rows(tables[datetime(2026, 9, 13, 14)]) == [(datetime(2026, 9, 13, 14), "en", "Lisbon", 7, 0)]
    assert tables[datetime(2026, 9, 13, 1)].num_rows == 0


def test_sql_str_escapes_quotes():
    from pathlib import Path

    from lookedup.transform import _sql_str

    assert _sql_str(Path("/tmp/o'clock")) == "'/tmp/o''clock'"
