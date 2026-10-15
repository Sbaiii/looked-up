"""The language ranking file: order by rank and the top_n cut."""
from __future__ import annotations

from datetime import date

import yaml

from lookedup import languages as L
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


def test_last_full_days_end_yesterday():
    days = L.last_full_days(3, today=date(2026, 10, 8))
    assert days == [date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)]


def test_fetch_siteinfo(monkeypatch):
    reply = {"query": {"general": {"mainpage": "Wikipédia:Accueil principal"},
                       "namespaces": {"0": {"id": 0, "name": ""}, "2": {"id": 2, "name": "Utilisateur", "canonical": "User"},
                                      "14": {"id": 14, "name": "Catégorie", "canonical": "Category"}},
                       "namespacealiases": [{"id": 2, "alias": "Utilisatrice"}, {"id": 0, "alias": "ignored"}]}}
    monkeypatch.setattr(L, "_get_json", lambda url, params: reply)
    info = L.fetch_siteinfo("fr")
    assert info["main_page"] == "Wikipédia:Accueil_principal"
    assert info["namespaces"] == ["catégorie", "category", "user", "utilisateur", "utilisatrice"]


def test_fetch_names(monkeypatch):
    reply = {"sitematrix": {"count": 2, "0": {"code": "fr", "localname": "French", "name": "français"},
                            "1": {"code": "ja", "localname": "Japanese", "name": "日本語"}, "specials": []}}
    monkeypatch.setattr(L, "_get_json", lambda url, params: reply)
    assert L.fetch_names() == {"fr": ("French", "français"), "ja": ("Japanese", "日本語")}


def test_fetch_speakers_survives_a_failure(monkeypatch):
    class Down:
        def get(self, *a, **k):
            raise ConnectionError("query service down")

    monkeypatch.setattr(L, "session", lambda: Down())
    assert L.fetch_speakers(["en", "fr"]) == {}


def test_day_aggregate_sums_desktop_and_mobile(tmp_path):
    import bz2

    import duckdb

    lines = ["fr.wikipedia Lisbonne 1 desktop 30 A30\n", "fr.wikipedia Lisbonne 1 mobile-web 50 A50\n",
             "fr.wikipedia Lisbonne 1 mobile-app 20 A20\n", "fr.wiktionary Lisbonne 1 desktop 99 A99\n",
             "en.wikipedia Lisbon 2 desktop 7 A7\n"]
    src = tmp_path / "day.bz2"
    src.write_bytes(bz2.compress("".join(lines).encode()))
    out = tmp_path / "agg.parquet"
    L._day_aggregate(src, out)
    rows = dict(((l, t), (d, m)) for l, t, d, m in duckdb.sql(f"SELECT * FROM '{out}'").fetchall())
    assert rows[("fr", "Lisbonne")] == (30, 70)                        # web and app both count as mobile
    assert rows[("en", "Lisbon")] == (7, None)
    assert len(rows) == 2                                               # Wiktionary is not a Wikipedia
