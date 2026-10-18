from __future__ import annotations

from datetime import date, datetime

from lookedup.evaluation.ground_truth_v2 import DEATH_WORDS, _boxes, kickoff_utc, parse_deaths, place_parts

DEATHS = """==August 2026==
===1===
*[[Alexeis Argilagos]], 51, Cuban Olympic volleyball player ([[Volleyball at the 2000 Summer Olympics|2000]]).
*[[Beitia (footballer)|Beitia]], 89, Spanish footballer ([[Barakaldo CF|Barakaldo]]).
===2===
*[[Hayden Panettiere]], 37, American actress.
"""

BOX = """<section begin="3rd" />{{#invoke:football box|main
|date={{Start date|2026|7|18}}
|time=5:00&nbsp;p.m. [[UTC−04:00|UTC−4]]
|team1={{#invoke:flag|fb-rt|FRA}}
|team2={{#invoke:flag|fb|ENG}}
}}<section end="3rd" />"""


def test_parse_deaths_takes_first_link_and_day():
    rows = parse_deaths(DEATHS, 2026, 8)
    assert [(r["date"], r["title"]) for r in rows] == [
        (date(2026, 8, 1), "Alexeis Argilagos"), (date(2026, 8, 1), "Beitia (footballer)"),
        (date(2026, 8, 2), "Hayden Panettiere")]


def test_death_words():
    assert DEATH_WORDS.search("Infobox edit - death date") and DEATH_WORDS.search("added DOD")
    assert DEATH_WORDS.search("Fixed: died on 3 August") and not DEATH_WORDS.search("copyedit, refs")


def test_football_box_and_kickoff():
    [box] = _boxes(BOX)
    assert box["team1"].endswith("FRA}}") and box["date"].startswith("{{Start date")
    assert kickoff_utc(box["date"], box["time"]) == datetime(2026, 7, 18, 21, 0)
    assert kickoff_utc("{{Start date|2026|7|9}}", "8:00&nbsp;p.m. [[UTC−05:00|UTC−5]]") == datetime(2026, 7, 10, 1, 0)
    assert kickoff_utc("{{Start date|2026|7|19}}", "15:00 [[Eastern Daylight Time|EDT]] ([[UTC−4]])") == datetime(2026, 7, 19, 19)
    assert kickoff_utc("{{Start date|2026|7|19}}", "TBD") is None


def test_place_parts():
    assert place_parts("45 km SW of Ambon, Indonesia") == ("Ambon", "Indonesia")
    assert place_parts("Kermadec Islands region") == (None, "Kermadec Islands region")


def test_great_circle_distance():
    from lookedup.evaluation.ground_truth_v2 import _km
    assert _km(0, 0, 0, 0) == 0
    assert abs(_km(0, 0, 0, 1) - 111.2) < 0.5                         # one degree along the equator
    assert abs(_km(48.8566, 2.3522, 51.5074, -0.1278) - 344) < 5     # Paris to London
    assert _km(None, 0, 0, 0) == float("inf")


class _Json:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def test_usgs_quakes(monkeypatch):
    import lookedup.evaluation.ground_truth_v2 as G

    feed = {"features": [{"id": "us7000t1bu", "properties": {"mag": 7.3, "place": "60 km WSW of Puerto Madero, Mexico",
                                                            "time": 1784386119881}, "geometry": {"coordinates": [-93.2, 14.4, 30]}},
                         {"id": "x", "properties": {"mag": 6.1, "place": None, "time": 0}, "geometry": {"coordinates": [0, 0, 0]}}]}
    monkeypatch.setattr(G, "_get", lambda url, params: _Json(feed))
    q = G.usgs_quakes(datetime(2026, 7, 16), datetime(2026, 10, 7), 6.0)
    assert q[0]["usgs_id"] == "us7000t1bu" and q[0]["mag"] == 7.3 and (q[0]["lon"], q[0]["lat"]) == (-93.2, 14.4)
    assert q[0]["origin"].tzinfo is None and q[0]["origin"].year == 2026
    assert q[1]["place"] == "" and q[1]["origin"] == datetime(1970, 1, 1)


def test_wikidata_quakes(monkeypatch):
    import lookedup.evaluation.ground_truth_v2 as G

    W = "http://www.wikidata.org/entity/"
    rows = [{"item": {"value": W + "Q140616464"}, "t": {"value": "2026-07-17T00:00:00Z"},
             "coord": {"value": "Point(-93.2 14.4)"}, "mag": {"value": "7.3"}, "country": {"value": W + "Q96"}},
            {"item": {"value": W + "Q140616464"}, "t": {"value": "2026-07-17T00:00:00Z"}, "country": {"value": W + "Q774"}},
            {"item": {"value": W + "Q1"}, "t": {"value": "2026-08-01T00:00:00Z"}}]
    monkeypatch.setattr(G, "_sparql", lambda q: rows)
    got = {q["qid"]: q for q in G.wikidata_quakes(date(2026, 7, 16), date(2026, 10, 7))}
    assert got[140616464]["countries"] == {96, 774} and (got[140616464]["lon"], got[140616464]["lat"]) == (-93.2, 14.4)
    assert got[140616464]["mag"] == 7.3 and got[140616464]["date"] == "2026-07-17"
    assert got[1]["lon"] is None and got[1]["mag"] is None and got[1]["countries"] == set()


def test_first_sitelink_created(monkeypatch):
    import lookedup.evaluation.ground_truth_v2 as G

    def get(url, params):
        if "wikidata" in url:
            return _Json({"entities": {"Q9": {"sitelinks": {"enwiki": {"title": "Quake"}, "eswiki": {"title": "Sismo"}}}}})
        ts = "2026-08-10T13:00:00Z" if url.startswith("https://en.") else "2026-08-10T12:20:00Z"
        return _Json({"query": {"pages": [{"revisions": [{"timestamp": ts}]}]}})

    monkeypatch.setattr(G, "_get", get)
    assert G.first_sitelink_created(9, ["en", "es"]) == datetime(2026, 8, 10, 12, 20)
    monkeypatch.setattr(G, "_get", lambda url, params: _Json({"entities": {"Q9": {}}}))
    assert G.first_sitelink_created(9, ["en"]) is None
