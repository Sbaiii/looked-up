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

    with open(Path(__file__).parent / "fixtures" / "current_events_sample.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
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


def test_resolve_qids_batches(monkeypatch):
    import lookedup.evaluation.ground_truth as gt

    empty = {"query": {"pages": []}}
    s = _Session([_Reply(data=empty)] * 3)
    monkeypatch.setattr(gt, "session", lambda: s)
    monkeypatch.setattr(gt.time, "sleep", lambda s: None)
    gt.resolve_qids("en", [f"T{i}" for i in range(5)], batch=2)
    assert [c["titles"].count("|") + 1 for c in s.calls] == [2, 2, 1]


def test_build_marks_major_pairs(tmp_path, monkeypatch):
    import json

    import pyarrow as pa
    import pyarrow.parquet as pq

    import lookedup.analytics.entities as E
    import lookedup.evaluation.ground_truth as gt
    from lookedup.analytics.config import load

    wiki = "== Sports ==\n* [[Lisbon]] hosts the [[Final]].\n** [[Week]] note\n"
    monkeypatch.setattr(gt, "fetch_day", lambda d: wiki)
    monkeypatch.setattr(gt.time, "sleep", lambda s: None)
    monkeypatch.setattr(gt, "resolve_qids", lambda lang, titles: {"Lisbon": 597, "Final": 7, "Week": 23387})
    sl = tmp_path / "sitelinks.parquet"
    pq.write_table(pa.table({"lang": ["en", "fr", "pt", "de", "en"], "title": ["L", "L", "L", "L", "F"],
                             "qid": [597, 597, 597, 597, 7]}), sl)
    cfg = load()
    generic = int(next(iter(cfg.raw["generic_classes"]))[1:])            # e.g. a country is a generic link
    monkeypatch.setattr(E, "fetch_claims", lambda qids, cache: pa.table({"qid": [597, 7, 23387], "label_en": [None] * 3,
        "claims_json": [json.dumps({"P31": [515]}), json.dumps({"P31": [1]}), json.dumps({"P31": [generic]})]}))
    res = gt.build(date(2026, 8, 10), date(2026, 8, 10), sl, tmp_path / "c.parquet", tmp_path / "gt.parquet", cfg)
    rows = {r["link_title"]: r for r in pq.read_table(tmp_path / "gt.parquet").to_pylist()}
    assert res["days"] == 1 and res["resolved"] == 3
    assert rows["Week"]["is_generic"] and not rows["Week"]["is_major"]
    assert rows["Lisbon"]["is_major"] == (4 >= cfg.raw["evaluation"]["major_min_languages"])
    assert not rows["Final"]["is_major"]                                    # linked in one language only
