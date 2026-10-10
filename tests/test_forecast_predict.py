from __future__ import annotations

from datetime import datetime, timedelta

import duckdb
import numpy as np

from lookedup.forecast import train as T
from lookedup.forecast.predict import forecast_open

T0 = datetime(2026, 10, 10, 2)


class Stub:
    def __init__(self, value):
        self.value = value

    def predict(self, X):
        return np.full(len(X), self.value)


def _con(breadth_wide):
    con = duckdb.connect()
    con.execute("CREATE TABLE _fev(event_id VARCHAR, qid BIGINT, start_hour TIMESTAMP, lead_lang VARCHAR, breadth INT, "
                "event_class VARCHAR, category VARCHAR)")
    con.execute("INSERT INTO _fev VALUES ('young', 1, ?, 'en', 2, 'multi_language', 'human'), "
                "('wide', 2, ?, 'en', ?, 'multi_language', 'human')", [T0, T0, breadth_wide])
    con.execute("CREATE TABLE _sp(qid BIGINT, lang VARCHAR, title VARCHAR, ts_hour_start TIMESTAMP, surprise DOUBLE, "
                "views INT, baseline_median DOUBLE)")
    rows = [(1, "en", 0), (1, "fr", 1)] + [(2, l, h) for l, h in [("en", 0), ("fr", 0), ("de", 1), ("es", 1), ("it", 2)]]
    con.executemany("INSERT INTO _sp VALUES (?, ?, ?, ?, 20, 500, 10)",
                    [(q, l, f"{l}{q}", T0 + timedelta(hours=h)) for q, l, h in rows])
    con.execute("CREATE TABLE _fviews AS SELECT lang, title, ts_hour_start, views, baseline_median FROM _sp")
    con.execute("CREATE TABLE _fdims(qid BIGINT, entity_class VARCHAR, n_languages INT)")
    con.execute("INSERT INTO _fdims VALUES (1, 'human', 10), (2, 'human', 25)")
    return con


def _models():
    enc = T.Encoder({"lead_lang": ["en"], "entity_class": ["human"]})
    m = {f"{t}_t{k}": (Stub(0.6), enc, None) for t in T.TARGETS for k in T.OFFSETS}
    m |= {"m2_excess_next24": (Stub(np.log1p(5000)), enc, None), "m2_fade_hours": (Stub(np.log1p(4)), enc, None)}
    return m


def test_open_events_use_the_oldest_available_offset_and_skip_reached_tiers():
    events = [{"event_id": "young", "qid": 1, "start_hour": T0, "lead_lang": "en", "breadth": 2, "event_class": "multi_language"},
              {"event_id": "wide", "qid": 2, "start_hour": T0, "lead_lang": "en", "breadth": 5, "event_class": "multi_language"}]
    now = T0 + timedelta(hours=6)
    out = forecast_open(_con(5), events, now, last_hour=T0 + timedelta(hours=5), manifest={"version": "v1"}, models=_models())
    young, wide = out["young"], out["wide"]
    assert young["offset_h"] == 3 and young["p_international"] == 0.6 and young["model_version"] == "v1"
    assert "p_international" not in wide and wide["p_planetary"] == 0.6      # already international
    assert young["predicted_excess_24h"] == 5000 and young["fade_eta_hours"] == 4.0
    assert young["fade_eta"] == "2026-10-10T10:00Z"                           # t0 = 03:00 (fr), T = 06:00, + 4 h


def test_too_young_for_any_snapshot_or_older_than_a_day_gets_nothing():
    events = [{"event_id": "young", "qid": 1, "start_hour": T0, "lead_lang": "en", "breadth": 2, "event_class": "multi_language"}]
    assert forecast_open(_con(5), events, T0 + timedelta(hours=1), last_hour=T0, manifest={}, models=_models()) == {}
    assert forecast_open(_con(5), events, T0 + timedelta(hours=30), last_hour=T0 + timedelta(hours=29), manifest={},
                         models=_models()) == {}
