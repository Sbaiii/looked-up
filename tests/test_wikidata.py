from __future__ import annotations

import gzip

import pyarrow.parquet as pq

from lookedup.wikidata import build_sitelinks, parse_sitelinks, site_id

DUMP = b"""-- MariaDB dump
INSERT INTO `wb_items_per_site` VALUES
(55,3596065,'abwiki','\xd0\x8f\xd1\x8c\xd0\xb3\xd1\x8c\xd0\xb0\xd1\x80\xd0\xb4\xd0\xb0'),
(1,597,'enwiki','Lisbon'),
(2,597,'frwiki','Lisbonne'),
(3,597,'zh_yuewiki','\xe9\x87\x8c\xe6\x96\xaf\xe6\x9c\xac'),
(4,90,'enwiki','Paris'),
(5,123,'enwiki','Rock \\'n\\' roll'),
(6,8,'commonswiki','Category:Lisbon'),
(7,9,'enwiktionary','Lisbon');
"""


def test_site_id():
    assert site_id("en") == "enwiki"
    assert site_id("zh-yue") == "zh_yuewiki"


def test_parse_keeps_only_requested_sites():
    rows = list(parse_sitelinks(DUMP.splitlines(), {b"enwiki": "en", b"zh_yuewiki": "zh-yue"}))
    assert ("en", "Lisbon", 597) in rows
    assert ("zh-yue", "里斯本", 597) in rows
    assert ("en", "Rock_'n'_roll", 123) in rows   # SQL escapes removed, spaces -> underscores
    assert all(lang in ("en", "zh-yue") for lang, _, _ in rows)
    assert len(rows) == 4


def test_build_sitelinks_sorted_parquet(tmp_path):
    dump = tmp_path / "dump.sql.gz"
    with gzip.open(dump, "wb") as f:
        f.write(DUMP)
    out = tmp_path / "sitelinks.parquet"
    counts = build_sitelinks(["en", "fr"], out, dump=dump)
    assert counts == {"en": 3, "fr": 1}
    t = pq.read_table(out)
    assert t.column_names == ["lang", "title", "qid"]
    assert list(zip(t["lang"].to_pylist(), t["title"].to_pylist(), strict=True)) == sorted(
        zip(t["lang"].to_pylist(), t["title"].to_pylist(), strict=True))


def test_join_coverage(tmp_path):
    from datetime import datetime

    import pyarrow as pa

    from lookedup.wikidata import join_coverage

    day = tmp_path / "day.parquet"
    pq.write_table(pa.table({"ts_hour_start": [datetime(2026, 10, 1, 10)] * 3 + [datetime(2026, 10, 1, 20)],
                             "lang": ["en", "en", "fr", "en"], "title": ["Lisbon", "Nowhere", "Lisbonne", "Lisbon"],
                             "views_desktop": [60, 30, 5, 1000], "views_mobile": [40, 10, 5, 0]}), day)
    sl = tmp_path / "sitelinks.parquet"
    pq.write_table(pa.table({"lang": ["en", "fr"], "title": ["Lisbon", "Lisbonne"], "qid": [597, 597]}), sl)
    rows = join_coverage([str(day)], str(sl), until=datetime(2026, 10, 1, 12))
    assert rows == [("en", 140, 100, 71.4), ("fr", 10, 10, 100.0)]
    assert join_coverage([str(day)], str(sl), since=datetime(2026, 10, 1, 20))[0] == ("en", 1000, 1000, 100.0)


def test_build_sitelinks_writes_in_batches(tmp_path, monkeypatch):
    import lookedup.wikidata as W

    monkeypatch.setattr(W, "BATCH", 2)
    rows = ",".join(f"({i},{i},'enwiki','Title {i}')" for i in range(5))
    dump = tmp_path / "wb.sql.gz"
    with gzip.open(dump, "wt") as f:
        f.write(f"INSERT INTO `wb_items_per_site` VALUES {rows};\n")
    out = tmp_path / "s.parquet"
    assert W.build_sitelinks(["en"], out, dump) == {"en": 5}
    assert pq.read_table(out).num_rows == 5


def test_build_sitelinks_exact_batches(tmp_path, monkeypatch):
    import lookedup.wikidata as W

    monkeypatch.setattr(W, "BATCH", 2)
    rows = ",".join(f"({i},{i},'enwiki','Title {i}')" for i in range(4))
    dump = tmp_path / "wb.sql.gz"
    with gzip.open(dump, "wt") as f:
        f.write(f"INSERT INTO `wb_items_per_site` VALUES {rows};\n")
    out = tmp_path / "s.parquet"
    assert W.build_sitelinks(["en"], out, dump) == {"en": 4}
    assert pq.read_table(out)["title"].to_pylist() == [f"Title_{i}" for i in range(4)]


def test_site_id_hyphens():
    from lookedup.wikidata import site_id

    assert site_id("zh-min-nan") == "zh_min_nanwiki" and site_id("en") == "enwiki"
