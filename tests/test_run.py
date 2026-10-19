"""The Phase 2 evaluation runner: its CSV writer and how evaluate() wires the metrics into its outputs."""

from __future__ import annotations

import csv
import json

import duckdb
import pytest

from lookedup.evaluation import run


def _read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def test_csv_writes_dicts_under_their_keys(tmp_path):
    out = tmp_path / "sub" / "a.csv"
    run._csv(out, [{"lang": "en", "n": 3}, {"lang": "fr", "n": 1}])
    assert _read(out) == [["lang", "n"], ["en", "3"], ["fr", "1"]]


def test_csv_writes_tuples_under_a_header(tmp_path):
    run._csv(tmp_path / "b.csv", [("en", 3)], ["lead_lang", "events"])
    run._csv(tmp_path / "c.csv", [], ["lead_lang", "events"])
    run._csv(tmp_path / "d.csv", [("en", 3)])
    assert _read(tmp_path / "b.csv") == [["lead_lang", "events"], ["en", "3"]]
    assert _read(tmp_path / "c.csv") == [["lead_lang", "events"]]                 # empty rows still get the header
    assert _read(tmp_path / "d.csv") == [["en", "3"]]


@pytest.fixture
def stubbed(tmp_path, monkeypatch):
    """An in-memory warehouse with three events and every metric replaced by a fixed value."""
    from types import SimpleNamespace

    from lookedup.evaluation import metrics

    con = duckdb.connect()
    con.execute("ATTACH ':memory:' AS wh")
    con.execute("""CREATE TABLE wh.main.fct_attention_events AS SELECT * FROM (VALUES
        ('e1', 1, 'Big', 'death', TIMESTAMP '2026-08-01 10:00', 'en', 9, 12.34, 9000, ['en', 'fr']),
        ('e2', 2, 'In portal', 'sports', TIMESTAMP '2026-08-02 10:00', 'es', 5, 8.0, 50000, ['es']),
        ('e3', 3, 'Too early', 'other', TIMESTAMP '2026-07-01 10:00', 'de', 3, 4.0, 70000, ['de']))
        t(event_id, qid, label_en, category, start_hour, lead_lang, breadth, peak_intensity, excess_views, languages)""")
    con.execute("CREATE TABLE majors AS SELECT 1 AS x UNION ALL SELECT 2")
    con.execute("CREATE TABLE majors_s2 AS SELECT 1 AS x")
    con.execute("CREATE TABLE portal_qids AS SELECT 2 AS qid, DATE '2026-08-03' AS date")
    monkeypatch.setattr(metrics, "open_context", lambda *a: SimpleNamespace(con=con))
    monkeypatch.setattr(run, "OUT", tmp_path)
    recall = {"recall": 0.8, "pairs": 2, "detected": 1}
    for name, value in {"event_count": 3, "recall": recall, "precision_proxy": {"share": 0.5},
                        "recall_by_section": [("Sports", 2, 1, 0.5)], "lead_counts": [("en", 1)],
                        "variant_events": "primary_events", "h4_spread": {"verdict": "rejected"},
                        "h2_lead_language": {"verdict": "rejected"},
                        "ablation_grid": [{"r3": 6, "winner": False}, {"r3": 8, "winner": True}],
                        "detection_delays": {"rows": [], "median_h": None}}.items():
        monkeypatch.setattr(metrics, name, lambda *a, _v=value, **k: _v)
    return tmp_path


def test_evaluate_writes_its_outputs(stubbed):
    res = run.evaluate()
    assert res["events_total"] == 3 and res["major_pairs"] == 2 and res["s2_story_headers"]["pairs"] == 1
    assert res["h1"]["verdict"] == "supported" and res["ablation_winner"] == {"r3": 8, "winner": True}
    assert json.loads((stubbed / "phase2_metrics.json").read_text())["events_total"] == 3
    review = _read(stubbed / "nonportal_top30.csv")
    assert [r[1] for r in review[1:]] == ["1"]                    # e2 is in the portal, e3 before the evaluation period
    assert review[1][-1] == "en fr" and review[1][7] == "12.3"
    assert _read(stubbed / "detection_delays.csv") == [["note"], ["no timestamps"]]
