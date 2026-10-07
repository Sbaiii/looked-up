from __future__ import annotations

from datetime import datetime

import pytest

from lookedup import dumps
from lookedup.parse import (
    ArticleFilter,
    decode_pvc_hours,
    keep_row,
    namespace_prefix,
    normalize_title,
    parse_dump_line,
    parse_project,
    parse_pvc_line,
    parse_pvc_project,
)


@pytest.mark.parametrize("code,expected", [
    ("en", ("en", False)),
    ("en.m", ("en", True)),
    ("zh-yue", ("zh-yue", False)),
    ("zh-yue.m", ("zh-yue", True)),
    ("en.d", None),        # Wiktionary
    ("en.m.d", None),      # mobile Wiktionary
    ("de.b", None),        # Wikibooks
    ("commons.m", None),   # Commons, not a language
    ("meta.m", None),
    ("www.wd", None),      # Wikidata
    ("EN", None),
    ("", None),
])
def test_parse_project(code, expected):
    assert parse_project(code) == expected


@pytest.mark.parametrize("wiki,access,expected", [
    ("fr.wikipedia", "desktop", ("fr", False)),
    ("fr.wikipedia", "mobile-web", ("fr", True)),
    ("fr.wikipedia", "mobile-app", ("fr", True)),
    ("fr.wiktionary", "desktop", None),
    ("commons.wikipedia", "desktop", None),
    ("fr.wikipedia", "unknown", None),
])
def test_parse_pvc_project(wiki, access, expected):
    assert parse_pvc_project(wiki, access) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Lisbon", "Lisbon"),
    ("Caf%C3%A9", "Café"),                         # percent-encoded UTF-8 is decoded
    ("100%_Love_(2011_film)", "100%_Love_(2011_film)"),  # literal % kept
    ("A%2520B", "A%20B"),                          # decoded exactly once
    ("Bad%E2%82", "Bad%E2%82"),                    # invalid UTF-8 -> raw title
    ("New York", "New_York"),                      # spaces -> underscores
    ("a+b", "a+b"),                                # '+' is not a space
])
def test_normalize_title(raw, expected):
    assert normalize_title(raw) == expected


def test_namespace_prefix():
    assert namespace_prefix("Spécial:Recherche") == "spécial"
    assert namespace_prefix("Wikipedia_talk:Foo") == "wikipedia talk"
    assert namespace_prefix("Lisbon") is None
    assert namespace_prefix(":Foo") is None


@pytest.mark.parametrize("lang,title,ok", [
    ("en", "Lisbon", True),
    ("en", "Star_Wars:_Episode_IV_–_A_New_Hope", True),   # colon, but not a namespace
    ("en", "Main_Page", False),
    ("en", "Special:Search", False),
    ("en", "special:Search", False),                       # case-insensitive prefix
    ("en", "Talk:Lisbon", False),
    ("en", "File:Foo.jpg", False),
    ("en", "Draft:Foo", False),
    ("en", "-", False),
    ("fr", "Spécial:Recherche", False),                    # localised namespace
    ("fr", "Wikipédia:Accueil_principal", False),          # localised main page
    ("fr", "Main_Page", False),
    ("fr", "Utilisateur:Foo", False),
    ("fr", "Paris", True),
    ("de", "Benutzer_Diskussion:Foo", False),
    ("de", "Wikipedia:Hauptseite", False),
    ("ja", "特別:検索", False),
    ("ja", "メインページ", False),
    ("ja", "東京", True),
    ("es", "Especial:Buscar", False),
    ("ar", "خاص:بحث", False),
])
def test_is_article(article_filter, lang, title, ok):
    assert article_filter.is_article(lang, title) is ok


def test_unknown_language_falls_back_to_canonical_namespaces():
    f = ArticleFilter()
    assert not f.is_article("xx", "Special:Search")
    assert not f.is_article("xx", "Main_Page")
    assert f.is_article("xx", "Foo")


@pytest.mark.parametrize("d,m,ok", [(5, 0, True), (0, 5, True), (2, 3, True), (2, 2, False), (0, 0, False)])
def test_retention_rule(d, m, ok):
    assert keep_row(d, m) is ok


def test_parse_dump_line():
    assert parse_dump_line("en Main_Page 42 0\n") == ("en", "Main_Page", 42)
    assert parse_dump_line("en Main Page 42 0") is None
    assert parse_dump_line("en Foo x 0") is None


def test_parse_pvc_line_handles_5_and_6_columns():
    assert parse_pvc_line("en.wikipedia Lisbon 18044 desktop 7 A1C6") == ("en.wikipedia", "Lisbon", "desktop", "A1C6")
    assert parse_pvc_line("en.wikipedia Lisbon desktop 7 A1C6") == ("en.wikipedia", "Lisbon", "desktop", "A1C6")
    assert parse_pvc_line("garbage") is None


def test_decode_pvc_hours():
    assert decode_pvc_hours("A3C12X1") == {0: 3, 2: 12, 23: 1}
    assert decode_pvc_hours("") == {}


def test_ts_hour_start_is_file_timestamp_minus_one_hour():
    # file name = END of the covered hour (verified against the REST API, ADR 0008)
    assert dumps.hour_start_from_name("pageviews-20261007-100000.gz") == datetime(2026, 10, 7, 9)
    assert dumps.hour_start_from_name("pageviews-20261008-000000.gz") == datetime(2026, 10, 7, 23)
    assert dumps.file_name(datetime(2026, 10, 7, 23)) == "pageviews-20261008-000000.gz"
    assert dumps.file_url(datetime(2026, 9, 30, 23)).endswith("/2026/2026-10/pageviews-20261001-000000.gz")


def test_lag_minutes():
    f = dumps.HourlyFile(name="x", url="x", ts_hour_start=datetime(2026, 10, 7, 9),
                         posted=datetime(2026, 10, 7, 12, 29), size=1)
    assert f.lag_minutes == 149
