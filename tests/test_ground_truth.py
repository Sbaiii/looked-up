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


def test_committed_sample_is_consistent():
    import csv

    rows = list(csv.DictReader(open(Path(__file__).parent / "fixtures" / "current_events_sample.csv", encoding="utf-8")))
    assert len(rows) == 50
    for r in rows:
        major = r["is_major"] == "true"
        if major:  # major = resolved, not generic, >= 3 of our languages
            assert r["qid"] and r["is_generic"] == "false" and int(r["n_languages"]) >= 3


class _Reply:
    def __init__(self, status=200, text="", data=None):
        self.status_code, self.text, self._data = status, text, data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._data


class _Session:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        return self.replies.pop(0)


def test_fetch_day(monkeypatch):
    import lookedup.evaluation.ground_truth as gt

    s = _Session([_Reply(404), _Reply(200, "* item")])
    monkeypatch.setattr(gt, "session", lambda: s)
    assert gt.fetch_day(date(2026, 8, 10)) == ""
    assert gt.fetch_day(date(2026, 8, 11)) == "* item"
    assert s.calls[1]["title"] == "Portal:Current_events/2026_August_11"


def test_resolve_qids_follows_redirects(monkeypatch):
    import lookedup.evaluation.ground_truth as gt

    reply = {"query": {"normalized": [{"from": "lisbon", "to": "Lisbon"}],
                       "redirects": [{"from": "Lisbon", "to": "Lisboa"}],
                       "pages": [{"title": "Lisboa", "pageprops": {"wikibase_item": "Q597"}},
                                 {"title": "Nowhere", "missing": True}]}}
    monkeypatch.setattr(gt, "session", lambda: _Session([_Reply(data=reply)]))
    monkeypatch.setattr(gt.time, "sleep", lambda s: None)
    assert gt.resolve_qids("en", ["lisbon", "Nowhere"]) == {"lisbon": 597}
