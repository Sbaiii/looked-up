"""The H3 audit score on a tiny attached warehouse (blind labels joined to the automation flags)."""
from __future__ import annotations

import csv

import duckdb

from lookedup.analytics.config import load
from lookedup.evaluation import audit


def _write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _con():
    con = duckdb.connect()
    con.execute("ATTACH ':memory:' AS wh")
    con.execute("""CREATE TABLE wh.main.int_automation_flags AS SELECT * FROM (VALUES
        ('en', 'Bot', DATE '2026-08-10', true, true, false),
        ('en', 'News', DATE '2026-08-10', false, false, false)) t(lang, title, day, is_automated, is_low_mobile, is_flat)""")
    return con


def test_h3_score_is_inconclusive_with_few_non_events(tmp_path):
    sample = [{"unit_id": "u1", "lang": "en", "title": "Bot", "day": "2026-08-10"},
              {"unit_id": "u2", "lang": "en", "title": "News", "day": "2026-08-10"},
              {"unit_id": "u3", "lang": "en", "title": "Unknown", "day": "2026-08-10"}]
    labels = [{"unit_id": "u1", "label": "non_event"}, {"unit_id": "u2", "label": "event"}, {"unit_id": "u3", "label": "unsure"}]
    _write(tmp_path / "s.csv", sample)
    _write(tmp_path / "l.csv", labels)
    res = audit.score(_con(), load(), tmp_path / "s.csv", tmp_path / "l.csv")
    assert res["labels"] == {"event": 1, "non_event": 1, "unsure": 1}
    assert res["non_events_flagged"] == 1 and res["share_non_events_flagged"] == 1.0
    assert res["events_wrongly_flagged"] == 0 and res["by_rule"] == {"is_low_mobile": 1, "is_flat": 0}
    assert res["verdict"].startswith("inconclusive")


def test_h3_score_refuses_missing_or_unknown_labels(tmp_path):
    import pytest

    _write(tmp_path / "s.csv", [{"unit_id": "u1", "lang": "en", "title": "Bot", "day": "2026-08-10"}])
    _write(tmp_path / "l.csv", [{"unit_id": "u1", "label": "maybe"}])
    with pytest.raises(AssertionError):
        audit.score(_con(), load(), tmp_path / "s.csv", tmp_path / "l.csv")
    _write(tmp_path / "l.csv", [{"unit_id": "u2", "label": "event"}])
    with pytest.raises(AssertionError, match="every sampled unit"):
        audit.score(_con(), load(), tmp_path / "s.csv", tmp_path / "l.csv")


def test_h3_sample_is_seeded_with_96_hour_series(tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    monkeypatch.delenv("LOOKEDUP_PERIOD_END", raising=False)
    con = duckdb.connect()
    con.execute("ATTACH ':memory:' AS wh")
    con.execute("""CREATE TABLE wh.main.int_spikes AS
        SELECT 'en' AS lang, 'T' || i AS title, DATE '2026-08-10' AS day, 10.0 + i AS surprise FROM range(150) r(i)""")
    day = datetime(2026, 8, 10)
    con.execute("CREATE TABLE wh.main.stg_hourly(lang VARCHAR, title VARCHAR, day DATE, ts_hour_start TIMESTAMP, views BIGINT)")
    con.executemany("INSERT INTO wh.main.stg_hourly VALUES ('en', 'T5', ?, ?, ?)",
                    [((day - timedelta(days=3) + timedelta(hours=k)).date(), day - timedelta(days=3) + timedelta(hours=k), k)
                     for k in range(96)])
    n = audit.sample(con, load(), tmp_path / "a.csv")
    again = audit.sample(con, load(), tmp_path / "b.csv")
    assert n == again == 100 and (tmp_path / "a.csv").read_text() == (tmp_path / "b.csv").read_text()
    with open(tmp_path / "a.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [r["unit_id"] for r in rows[:2]] == ["u001", "u002"] and all(len(r["views_by_hour_d-3_to_d"].split()) == 96 for r in rows)
    t5 = [r for r in rows if r["title"] == "T5"]
    assert not t5 or t5[0]["views_by_hour_d-3_to_d"].split()[:3] == ["0", "1", "2"]


def test_run_audit_sample_writes_into_out(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from lookedup.evaluation import metrics, run

    seen = {}
    monkeypatch.setattr(run, "OUT", tmp_path)
    monkeypatch.setattr(metrics, "open_context", lambda w, c, cfg: SimpleNamespace(con="con"))
    monkeypatch.setattr(audit, "sample", lambda con, cfg, out: seen.update(con=con, out=out) or 7)
    assert run.audit_sample() == 7 and seen == {"con": "con", "out": tmp_path / "h3_sample.csv"}


def test_run_audit_score_writes_outputs(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from lookedup.evaluation import metrics, run

    monkeypatch.setattr(run, "OUT", tmp_path)
    monkeypatch.setattr(metrics, "open_context", lambda w, c, cfg: SimpleNamespace(con="con"))
    monkeypatch.setattr(audit, "score", lambda con, cfg, s, l: {"verdict": "inconclusive", "rows": [{"unit_id": "u1", "label": "event"}]})
    res = run.audit_score()
    assert res == {"verdict": "inconclusive"}
    assert json.loads((tmp_path / "h3_results.json").read_text()) == {"verdict": "inconclusive"}
    assert (tmp_path / "h3_audit.csv").read_text().splitlines() == ["unit_id,label", "u1,event"]
