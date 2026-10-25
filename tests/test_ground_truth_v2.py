from __future__ import annotations

from datetime import date, datetime, timedelta

from lookedup.evaluation.ground_truth_v2 import (
    DEATH_WORDS,
    _boxes,
    kickoff_utc,
    parse_deaths,
    place_parts,
)

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


def test_matches_resolve_qids(monkeypatch):
    import lookedup.evaluation.ground_truth_v2 as G

    monkeypatch.setattr(G, "football_matches", lambda page: [{"page": page, "kickoff": None, "teams": ["Spain", "Argentina"],
                                                              "match_article": page}])
    monkeypatch.setattr(G, "resolve_qids", lambda lang, titles: {"Spain": 29, "2026 FIFA World Cup final": 7})
    [m] = G.matches(["2026 FIFA World Cup final"])
    assert m["team_qids"] == [29] and m["match_qid"] == 7


class _Resp:
    def __init__(self, status=200, text="", payload=None):
        self.status_code, self.text, self._payload = status, text, payload

    def raise_for_status(self):
        import requests
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        if self._payload is None:
            raise ValueError("not JSON")
        return self._payload


class _Session:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params=None, **kw):
        self.calls.append(("GET", url, params))
        return self.responses.pop(0)

    def post(self, url, data=None, **kw):
        self.calls.append(("POST", url, data))
        return self.responses.pop(0)


def _fake(monkeypatch, *responses):
    import lookedup.evaluation.ground_truth_v2 as G

    s, sleeps = _Session(*responses), []
    monkeypatch.setattr(G, "session", lambda: s)
    monkeypatch.setattr(G.time, "sleep", sleeps.append)
    return G, s, sleeps


def test_get_retries_then_succeeds(monkeypatch):
    G, s, sleeps = _fake(monkeypatch, _Resp(503), _Resp(200, "ok"))
    assert G._get("https://x.test", {"a": 1}).text == "ok"
    assert len(s.calls) == 2 and sleeps == [3, 0.3]


def test_get_raises_after_retries(monkeypatch):
    import pytest
    import requests

    G, s, sleeps = _fake(monkeypatch, _Resp(500), _Resp(500), _Resp(500))
    with pytest.raises(requests.HTTPError):
        G._get("https://x.test", {}, retries=3)
    assert len(s.calls) == 3 and sleeps == [3, 6]


def test_raw_fetches_wikitext(monkeypatch):
    G, s, _ = _fake(monkeypatch, _Resp(200, "==August 2026=="))
    assert G._raw("Deaths in August 2026") == "==August 2026=="
    assert s.calls == [("GET", "https://en.wikipedia.org/w/index.php", {"title": "Deaths in August 2026", "action": "raw"})]


def test_sparql_retries_bad_json(monkeypatch):
    rows = [{"item": {"value": "http://www.wikidata.org/entity/Q1"}}]
    G, s, sleeps = _fake(monkeypatch, _Resp(200), _Resp(200, payload={"results": {"bindings": rows}}))
    assert G._sparql("SELECT ?item WHERE {}") == rows
    assert [c[0] for c in s.calls] == ["POST", "POST"] and s.calls[0][2] == {"query": "SELECT ?item WHERE {}"}
    assert sleeps == [5]


def test_sparql_gives_up(monkeypatch):
    import pytest
    import requests

    G, s, sleeps = _fake(monkeypatch, *[_Resp(429)] * 5)
    with pytest.raises(requests.HTTPError):
        G._sparql("SELECT 1")
    assert len(s.calls) == 5 and sleeps == [5, 10, 15, 20]


def test_parse_deaths_skips_unlinked_bullets():
    text = "*[[Too Early]], 90, before any day heading.\n===3===\n*An unnamed person, 70.\n*[[Real Person]], 61, writer.\n"
    assert [(r["date"], r["title"]) for r in parse_deaths(text, 2026, 8)] == [(date(2026, 8, 3), "Real Person")]


def test_first_sitelink_created_skips_pages_without_revisions(monkeypatch):
    import lookedup.evaluation.ground_truth_v2 as G

    def get(url, params):
        if "wikidata" in url:
            return _Json({"entities": {"Q9": {"sitelinks": {"enwiki": {"title": "Quake"}, "frwiki": {"title": "Séisme"}}}}})
        if url.startswith("https://fr."):
            return _Json({"query": {"pages": [{"missing": True}]}})
        return _Json({"query": {"pages": [{"revisions": [{"timestamp": "2026-08-10T15:00:00Z"}]}]}})

    monkeypatch.setattr(G, "_get", get)
    assert G.first_sitelink_created(9, ["en", "fr"]) == datetime(2026, 8, 10, 15)


def test_quakes_skip_far_and_late_articles(monkeypatch):
    import lookedup.evaluation.ground_truth_v2 as G

    origin = datetime(2026, 8, 10, 12, 0)
    monkeypatch.setattr(G, "usgs_quakes", lambda s, e, m: [{"usgs_id": "u1", "mag": 6.8, "place": "Alaska Peninsula",
                                                             "origin": origin, "lon": -158.0, "lat": 55.0}])
    monkeypatch.setattr(G, "wikidata_quakes", lambda s, e: [
        {"qid": 1, "date": "2026-08-10", "lon": 120.0, "lat": -8.0, "mag": 6.8, "countries": {252}},     # 12,000 km away
        {"qid": 3, "date": "2026-08-11", "lon": -158.1, "lat": 55.1, "mag": 6.7, "countries": {30}}])    # near, but late
    created = []
    monkeypatch.setattr(G, "first_sitelink_created", lambda qid, langs: created.append(qid) or origin + timedelta(hours=72))
    monkeypatch.setattr(G, "resolve_qids", lambda lang, names: {})
    [q] = G.quakes(origin - timedelta(days=1), origin + timedelta(days=1), ["en"])
    assert created == [3] and q["article_qid"] is None and q["article_created"] is None and q["article_countries"] == []
    assert (q["locality"], q["region"]) == (None, "Alaska Peninsula") and q["place_qids"] == []


def test_boxes_ignore_non_field_lines():
    text = "intro |x=1\n{{Football box\n|date=2026-07-18\n<!-- a comment -->\n|team1=FRA\n}}\n|team2=after the box\n"
    assert _boxes(text) == [{"date": "2026-07-18", "team1": "FRA"}]


def test_football_matches_without_a_team_link(monkeypatch):
    import lookedup.evaluation.ground_truth_v2 as G

    monkeypatch.setattr(G, "_raw", lambda page: BOX)
    monkeypatch.setattr(G, "_expand_links", lambda text: ["France national football team"] if "FRA" in text else ["Flag of TBD"])
    [m] = G.football_matches("2026 FIFA World Cup knockout stage")
    assert m["teams"] == ["France national football team"]


def test_km_symmetric():
    from lookedup.evaluation.ground_truth_v2 import _km

    assert _km(10, 20, 10, 20) == 0
    assert abs(_km(0, 0, 0, 10) - _km(0, 10, 0, 0)) < 1e-9


def test_death_words_whole_words():
    assert not DEATH_WORDS.search("deadline extended") and not DEATH_WORDS.search("rippling")
    assert DEATH_WORDS.search("RIP") and DEATH_WORDS.search("passed away")


def test_place_parts_without_comma():
    assert place_parts("Kermadec Islands region") == (None, "Kermadec Islands region")
