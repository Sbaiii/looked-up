"""The language-to-countries map behind the globe (ADR 0023), built from fake Wikidata rows."""
from __future__ import annotations

from lookedup import language_geo as G

WD = "http://www.wikidata.org/entity/"


def row(iso3, lang_q, name="X", num=None):
    return {"iso3": iso3, "lang": WD + lang_q, "name": name, **({"num": num} if num else {})}


def test_official_languages_map_to_countries():
    rows = [row("fra", "Q150", "France", "250"), row("BEL", "Q150", "Belgium", "056"), row("JPN", "Q5287", "Japan", "392")]
    by_lang, countries = G.build(rows, ["fr", "ja"])
    assert by_lang["fr"] == ["BEL", "FRA"] and by_lang["ja"] == ["JPN"]
    assert countries["FRA"] == {"name": "France", "num": "250"}
    only_fr, _ = G.build(rows, ["fr"])
    assert set(only_fr) == {"fr"}


def test_hand_check_is_applied():
    rows = [row("USA", "Q1321", "United States", "840"), row("MEX", "Q1321", "Mexico", "484")]
    by_lang, countries = G.build(rows, ["es", "zh"])
    assert "USA" not in by_lang["es"] and {"MEX", "URY", "PRI"} <= set(by_lang["es"])     # REMOVE and ADD for es
    assert by_lang["zh"] == ["CHN", "TWN"]
    assert countries["TWN"] == {"name": "Taiwan", "num": "158"}                         # filled in by hand


def test_numeric_codes_are_kept():
    rows = [row("FRA", "Q150", "France"), row("FRA", "Q150", "France", "250")]
    _, countries = G.build(rows, ["fr"])
    assert countries["FRA"]["num"] == "250"


def test_write_files(tmp_path, monkeypatch):
    import json

    import yaml

    monkeypatch.setattr(G, "GEO_FILE", tmp_path / "language_geo.yml")
    monkeypatch.setattr(G, "APP_GEO_FILE", tmp_path / "app" / "language_geo.json")
    by_lang = {"fr": ["BEL", "FRA"], "sr": ["SRB", "XKX"]}
    countries = {"BEL": {"name": "Belgium", "num": "056"}, "FRA": {"name": "France", "num": "250"},
                 "SRB": {"name": "Serbia", "num": "688"}, "XKX": {"name": "Kosovo", "num": None}}
    G.write(by_lang, countries)
    doc = yaml.safe_load((tmp_path / "language_geo.yml").read_text())
    assert doc["anchors"] == {"fr": "FRA", "sr": "SRB"} and doc["languages"]["fr"] == ["BEL", "FRA"]
    app = json.loads((tmp_path / "app" / "language_geo.json").read_text())
    assert sorted(app["languages"]["sr"]) == ["688", "XKX"]                 # Kosovo keeps its alpha-3 code


def test_fetch_flattens_bindings(monkeypatch):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": {"bindings": [{"iso3": {"value": "FRA"}, "lang": {"value": WD + "Q150"},
                                              "name": {"value": "France"}, "num": {"value": "250"}}]}}

    monkeypatch.setattr(G, "session", lambda: type("S", (), {"get": lambda self, *a, **k: R()})())
    assert G.fetch() == [{"iso3": "FRA", "lang": WD + "Q150", "name": "France", "num": "250"}]


def test_main_builds_and_writes(monkeypatch):
    import lookedup.languages as langs

    seen = {}
    monkeypatch.setattr(G, "fetch", lambda: [row("FRA", "Q150", "France", "250")])
    monkeypatch.setattr(langs, "active_codes", lambda: ["fr"])
    monkeypatch.setattr(G, "write", lambda by_lang, countries: seen.update(by_lang=by_lang, countries=countries))
    G.main()
    assert seen["by_lang"] == {"fr": ["FRA"]} and seen["countries"]["FRA"]["num"] == "250"


def test_iso_upper_and_late_numeric_code():
    rows = [row("prt", "Q5146", "Portugal"), row("PRT", "Q5146", "Portugal", "620")]
    by_lang, countries = G.build(rows, ["pt"])
    assert "PRT" in by_lang["pt"] and countries["PRT"]["num"] == "620"
