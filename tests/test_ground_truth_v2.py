from __future__ import annotations

from datetime import date, datetime, timedelta

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


def test_announcement_proxy(monkeypatch):
    import lookedup.evaluation.ground_truth_v2 as G

    revs = [{"timestamp": "2026-08-16T23:00:00Z", "comment": "copyedit"},
            {"timestamp": "2026-08-17T02:57:00Z", "comment": "added death date"},
            {"timestamp": "2026-08-17T03:10:00Z", "comment": "RIP"}]
    monkeypatch.setattr(G, "_get", lambda url, params: _Json({"query": {"pages": [{"revisions": revs}]}}))
    assert G.announcement_proxy("Hayden Panettiere", date(2026, 8, 17)) == datetime(2026, 8, 17, 2, 57)
    monkeypatch.setattr(G, "_get", lambda url, params: _Json({"query": {"pages": []}}))
    assert G.announcement_proxy("Nobody", date(2026, 8, 17)) is None


def test_deaths_keep_widely_known_people(monkeypatch):
    import lookedup.evaluation.ground_truth_v2 as G

    page = "===17===\n* [[Hayden Panettiere]], 37, American actress.\n* [[Local Figure]], 80, mayor.\n* [[Unresolved]], 50.\n"
    monkeypatch.setattr(G, "_raw", lambda title: page)
    monkeypatch.setattr(G, "resolve_qids", lambda lang, titles: {"Hayden Panettiere": 171571, "Local Figure": 9})
    monkeypatch.setattr(G, "announcement_proxy", lambda title, day: datetime(2026, 8, 17, 2, 57))
    rows = G.deaths([(2026, 8)], {171571: 28, 9: 2}, 5)
    assert [(r["title"], r["qid"], r["n_languages"]) for r in rows] == [("Hayden Panettiere", 171571, 28)]
    assert rows[0]["date"] == date(2026, 8, 17) and rows[0]["announcement"] == datetime(2026, 8, 17, 2, 57)


def test_quakes_match_nearby_new_articles(monkeypatch):
    import lookedup.evaluation.ground_truth_v2 as G

    origin = datetime(2026, 8, 10, 12, 0)
    monkeypatch.setattr(G, "usgs_quakes", lambda s, e, m: [{"usgs_id": "u1", "mag": 7.4, "place": "10 km E of San Jose, Colombia",
                                                             "origin": origin, "lon": -76.0, "lat": 4.5}])
    monkeypatch.setattr(G, "wikidata_quakes", lambda s, e: [
        {"qid": 1, "date": "2026-08-10", "lon": 120.0, "lat": -8.0, "mag": 7.4, "countries": {252}},     # far away
        {"qid": 2, "date": "2026-08-10", "lon": -76.1, "lat": 4.4, "mag": 7.3, "countries": {739}}])
    monkeypatch.setattr(G, "first_sitelink_created", lambda qid, langs: origin + timedelta(hours=3))
    monkeypatch.setattr(G, "resolve_qids", lambda lang, names: {"Colombia": 739})
    q = G.quakes(origin - timedelta(days=1), origin + timedelta(days=1), ["en", "es"])[0]
    assert q["article_qid"] == 2 and q["article_countries"] == [739]
    assert (q["locality"], q["region"]) == ("San Jose", "Colombia") and q["place_qids"] == [739]
    assert q["region_is_us_state"] is False


def test_expand_links_drop_files(monkeypatch):
    import lookedup.evaluation.ground_truth_v2 as G

    text = "[[File:Flag.svg|20px]] [[France national football team|France]] [[Image:x.png]] [[Kylian Mbappé]]"
    monkeypatch.setattr(G, "_get", lambda url, params: _Json({"expandtemplates": {"wikitext": text}}))
    assert G._expand_links("{{fb|FRA}}") == ["France national football team", "Kylian Mbappé"]


def test_football_matches(monkeypatch):
    import lookedup.evaluation.ground_truth_v2 as G

    monkeypatch.setattr(G, "_raw", lambda page: BOX)
    monkeypatch.setattr(G, "_expand_links", lambda text: ["Flag of France", "France national football team"] if "FRA" in text
                        else ["England national football team"])
    [m] = G.football_matches("2026 FIFA World Cup final")
    assert m["kickoff"] == datetime(2026, 7, 18, 21, 0)
    assert m["teams"][0] == "France national football team" and m["match_article"] == "2026 FIFA World Cup final"
    monkeypatch.setattr(G, "_raw", lambda page: BOX)
    assert G.football_matches("2026 FIFA World Cup knockout stage")[0]["match_article"] is None
