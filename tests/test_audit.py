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
