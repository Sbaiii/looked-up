"""The language ranking file: order by rank and the top_n cut."""
from __future__ import annotations

import yaml

from lookedup.languages import active_codes, active_languages


def test_active_languages_follow_rank_and_top_n(tmp_path):
    cfg = {"top_n": 2, "languages": [{"code": "fr", "rank": 2}, {"code": "en", "rank": 1, "name_en": "English"},
                                      {"code": "ja", "rank": 3}]}
    p = tmp_path / "languages.yml"
    p.write_text(yaml.safe_dump(cfg))
    langs = active_languages(p)
    assert [l.code for l in langs] == ["en", "fr"] and langs[0].name_en == "English" and langs[1].name_en is None
    assert active_codes(p) == ["en", "fr"]


def test_shipped_ranking():
    codes = active_codes()
    assert len(codes) == 30 and codes[0] == "en" and len(set(codes)) == 30
