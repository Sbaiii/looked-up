from __future__ import annotations

from datetime import date
from pathlib import Path

from lookedup.evaluation.ground_truth import page_title, parse_day

FIX = Path(__file__).parent / "fixtures" / "current_events_2026_August_10.wiki"
DAY = date(2026, 8, 10)


def test_page_title():
    assert page_title(date(2026, 7, 9)) == "Portal:Current_events/2026_July_9"


def test_parse_day_sections_entries_links():
    links = parse_day(FIX.read_text(encoding="utf-8"), DAY)
    sections = {l.section for l in links}
    assert {"Armed conflicts and attacks", "Disasters and accidents", "Politics and elections"} <= sections
    quake = [l for l in links if l.title == "2026 Colombia earthquake"]
    assert quake and quake[0].section == "Disasters and accidents" and quake[0].depth == 1
    assert any(l.title == "Chocó Department" and l.depth == 2 for l in links)
    # piped links keep the target, not the label; anchors are dropped
    assert any(l.title == "Supreme Leader of Iran" for l in links)
    # {{ill}} links point at the foreign-language article
    assert any(l.lang == "ar" and l.title == "فوزي المنصوري" for l in links)
    # external source links are not wikilinks
    assert not any(l.title.startswith("http") for l in links)


def test_parse_ignores_files_and_categories():
    links = parse_day("'''Sports'''\n*[[File:X.jpg]] [[Category:Y]] [[Real Madrid CF|Real Madrid]]\n", DAY)
    assert [(l.section, l.title) for l in links] == [("Sports", "Real Madrid CF")]
