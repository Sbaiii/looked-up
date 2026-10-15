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
