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
    assert info["namespaces"] == ["category", "catégorie", "user", "utilisateur", "utilisatrice"]   # plain sort: "o" < "é"


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
    rows = {(l, t): (d, m) for l, t, d, m in duckdb.sql(f"SELECT * FROM '{out}'").fetchall()}
    assert rows[("fr", "Lisbonne")] == (30, 70)                        # web and app both count as mobile
    assert rows[("en", "Lisbon")] == (7, None)
    assert len(rows) == 2                                               # Wiktionary is not a Wikipedia


def test_rank_languages_keeps_human_article_views(tmp_path, monkeypatch):
    import pyarrow as pa
    import pyarrow.parquet as pq

    day = date(2026, 10, 1)
    pq.write_table(pa.table({
        "lang": ["fr", "fr", "fr", "fr", "en", "en"],
        "title": ["Lisbonne", "Accueil", "Utilisateur:X", "Robot", "Lisbon", "Main_Page"],
        "desktop": [100, 900, 50, 5000, 300, 9000],
        "mobile": [100, 100, 0, 10, 300, 1000],
    }), tmp_path / f"agg-{day:%Y%m%d}.parquet")
    sites = {"fr": {"main_page": "Accueil", "namespaces": ["utilisateur"]}, "en": {"main_page": "Main_Page", "namespaces": []}}
    monkeypatch.setattr(L, "fetch_siteinfo", lambda lang: sites[lang])
    monkeypatch.setattr(L, "NAMESPACES_FILE", tmp_path / "namespaces.json")
    rows = {r["code"]: r for r in L.rank_languages([day], work_dir=tmp_path)}
    assert rows["en"]["human_views_7d"] == 600 and rows["fr"]["human_views_7d"] == 200   # main pages, User: and the bot-like page out
    assert rows["en"]["rank"] == 1 and rows["en"]["raw_rank"] == 1
    assert rows["fr"]["automated_share"] > 0 and rows["fr"]["non_article_share"] > 0
    assert rows["fr"]["cumulative_share_of_candidates"] == 1.0


def test_write_config(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "fetch_names", lambda: {"en": ("English", "English")})
    monkeypatch.setattr(L, "fetch_speakers", lambda codes: {"en": 753359540})
    ranking = [{"rank": 1, "code": "en", "human_views_7d": 10}, {"rank": 2, "code": "xx", "human_views_7d": 1}]
    out = tmp_path / "languages.yml"
    L.write_config(ranking, [date(2026, 10, 1), date(2026, 10, 7)], top_n=1, path=out)
    doc = yaml.safe_load(out.read_text())
    assert doc["top_n"] == 1 and doc["window"] == {"from": "2026-10-01", "to": "2026-10-07"}
    assert doc["languages"][0] == {"code": "en", "rank": 1, "name_en": "English", "name_native": "English",
                                   "speakers": 753359540, "human_views_7d": 10}
    assert doc["languages"][1]["name_en"] is None and doc["languages"][1]["speakers"] is None
    assert active_codes(out) == ["en"]


def test_get_json_retries(monkeypatch):
    import pytest
    import requests

    attempts = []

    class S:
        def get(self, url, params=None, timeout=None, **kw):
            attempts.append(1)
            if len(attempts) < 3:
                raise requests.ConnectionError("blip")
            return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: {"ok": True}})()

    monkeypatch.setattr(L, "session", lambda: S())
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    assert L._get_json("https://meta.wikimedia.org/w/api.php", {}) == {"ok": True} and len(attempts) == 3
    attempts.clear()
    monkeypatch.setattr(L, "session", lambda: type("D", (), {"get": lambda self, *a, **k: (_ for _ in ()).throw(requests.ConnectionError("down"))})())
    with pytest.raises(requests.ConnectionError):
        L._get_json("https://x", {}, retries=2)


def test_fetch_speakers_parses_bindings(monkeypatch):
    seen = {}

    class Up:
        def get(self, url, params=None, **kw):
            seen["query"] = params["query"]
            data = {"results": {"bindings": [{"code": {"value": "en"}, "speakers": {"value": "1.5E9"}},
                                             {"code": {"value": "fr"}, "speakers": {"value": "312000000"}}]}}
            return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: data})()

    monkeypatch.setattr(L, "session", lambda: Up())
    assert L.fetch_speakers(["en", "fr"]) == {"en": 1_500_000_000, "fr": 312_000_000}
    assert 'VALUES ?code { "en" "fr" }' in seen["query"]


def _download_pvc(tmp_path, monkeypatch):
    import bz2

    got = []

    def download(url, dest):
        got.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(bz2.compress(b"en.wikipedia Lisbon 2 desktop 70 A70\nfr.wikipedia Lisbonne 1 mobile-web 40 A40\n"))
        return dest

    monkeypatch.setattr(L, "download", download)
    monkeypatch.setattr(L, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(L, "fetch_siteinfo", lambda lang: {"main_page": "Main_Page", "namespaces": []})
    monkeypatch.setattr(L, "NAMESPACES_FILE", tmp_path / "namespaces.json")
    return got


def test_rank_languages_downloads_missing_days(tmp_path, monkeypatch):
    got = _download_pvc(tmp_path, monkeypatch)
    day = date(2026, 10, 2)
    rows = {r["code"]: r for r in L.rank_languages([day], work_dir=tmp_path / "work", keep_raw=False)}
    assert len(got) == 1 and got[0] == L.pvc_url(day)
    assert (tmp_path / "work" / "agg-20261002.parquet").exists()
    assert not list((tmp_path / "raw" / "pageview_complete").iterdir())      # the raw day is deleted
    assert rows["en"]["human_views_7d"] == 70 and rows["fr"]["human_views_7d"] == 40


def test_rank_languages_keeps_raw_and_reuses_aggregates(tmp_path, monkeypatch):
    got = _download_pvc(tmp_path, monkeypatch)
    day = date(2026, 10, 3)
    L.rank_languages([day], work_dir=tmp_path / "work")
    assert len(list((tmp_path / "raw" / "pageview_complete").iterdir())) == 1
    L.rank_languages([day], work_dir=tmp_path / "work")
    assert len(got) == 1                                                     # the aggregate is not rebuilt


def test_fetch_siteinfo_namespace_without_canonical(monkeypatch):
    reply = {"query": {"general": {"mainpage": "Main Page"},
                       "namespaces": {"100": {"id": 100, "name": "Portal", "canonical": ""}, "101": {"id": 101, "name": "Portal talk"}}}}
    monkeypatch.setattr(L, "_get_json", lambda url, params: reply)
    assert L.fetch_siteinfo("en")["namespaces"] == ["portal", "portal talk"]


def test_day_aggregate_skips_bad_lines(tmp_path):
    import bz2

    import duckdb

    lines = ["fr.wikipedia Lisbonne 1 desktop 30 A30\n", "fr.wikipedia broken\n", "fr.wikipedia Tab\tTitle 1 desktop 9 A9\n",
             "fr.wikipedia Paris 1 desktop x9 A9\n"]
    src = tmp_path / "day.bz2"
    src.write_bytes(bz2.compress("".join(lines).encode()))
    out = tmp_path / "agg.parquet"
    L._day_aggregate(src, out)
    assert duckdb.sql(f"SELECT lang, title, desktop FROM '{out}'").fetchall() == [("fr", "Lisbonne", 30)]
