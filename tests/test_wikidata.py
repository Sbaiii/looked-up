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
    assert list(zip(t["lang"].to_pylist(), t["title"].to_pylist())) == sorted(
        zip(t["lang"].to_pylist(), t["title"].to_pylist()))
