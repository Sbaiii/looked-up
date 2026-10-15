from __future__ import annotations

from datetime import date, datetime, timedelta
import json

import pytest

from lookedup.evaluation.metrics import to_jsonable


def test_json_fallback_for_dates_and_durations():
    doc = {"d": date(2026, 8, 17), "t": datetime(2026, 8, 17, 2), "lag": timedelta(hours=2)}
    assert json.loads(json.dumps(doc, default=to_jsonable)) == {"d": "2026-08-17", "t": "2026-08-17T02:00:00", "lag": 7200.0}
    with pytest.raises(TypeError):
        to_jsonable(object())


def _ctx(monkeypatch):
    import duckdb

    from lookedup.analytics.config import load
    from lookedup.evaluation.metrics import Context

    monkeypatch.delenv("LOOKEDUP_PERIOD_END", raising=False)
    con = duckdb.connect()
    con.execute("""CREATE TABLE majors AS SELECT * FROM (VALUES
        (DATE '2026-08-10', 1, ['Sports']), (DATE '2026-08-10', 2, ['Sports']),
        (DATE '2026-08-10', 3, ['Armed conflicts and attacks']), (DATE '2026-08-10', 4, ['Armed conflicts and attacks'])
        ) t(date, qid, sections)""")
    con.execute("""CREATE TABLE ev AS SELECT * FROM (VALUES
        (1, TIMESTAMP '2026-08-09 18:00', 'en', 'sports', 1.0),        -- 6 h before the day: inside
        (2, TIMESTAMP '2026-08-11 06:00', 'es', 'sports', 0.0),        -- 30 h after the day starts: inside
        (3, TIMESTAMP '2026-08-11 07:00', 'en', 'death', 3.0),         -- just outside
        (9, TIMESTAMP '2026-07-01 00:00', 'en', 'death', 2.0)          -- before the evaluation period
        ) t(qid, start_hour, lead_lang, category, median_spread_lag_hours)""")
    con.execute("CREATE TABLE portal_qids AS SELECT * FROM (VALUES (DATE '2026-08-12', 2), (DATE '2026-08-20', 3)) t(date, qid)")
    return Context(con, load())


def test_recall_window(monkeypatch):
    from lookedup.evaluation.metrics import recall

    ctx = _ctx(monkeypatch)
    assert recall(ctx, "ev", 6) == {"pairs": 4, "detected": 2, "recall": 0.5}
    assert recall(ctx, "ev", 7)["detected"] == 3


def test_recall_by_section(monkeypatch):
    from lookedup.evaluation.metrics import recall_by_section

    rows = {r[0]: r[1:] for r in recall_by_section(_ctx(monkeypatch), "ev", 6)}
    assert rows["Sports"] == (2, 2, 1.0) and rows["Armed conflicts and attacks"] == (2, 0, 0.0)
