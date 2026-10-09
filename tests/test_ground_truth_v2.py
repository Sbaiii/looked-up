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
