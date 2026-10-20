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


def test_no_models_means_no_forecasts(tmp_path):
    from datetime import datetime

    from lookedup.forecast import predict as P
    from lookedup.store import LocalStore

    manifest, models = P.load_models(LocalStore(tmp_path / "lake"), tmp_path)
    assert manifest == {} and models == {}
    assert P.forecast_open(None, [{"event_id": "E1"}], datetime(2026, 10, 10), datetime(2026, 10, 10), manifest, models) == {}


def test_published_models_load(tmp_path):
    import json

    from lookedup.forecast import predict as P
    from lookedup.store import LocalStore, Manifest

    rows = [{"n_sitelinks": i % 30, "lead_lang": "en", "entity_class": "human", "breadth_t": 2} for i in range(200)]
    enc = T.Encoder.fit(rows, features=["n_sitelinks", "breadth_t", "lead_lang"])
    y = np.array([int(r["n_sitelinks"] > 20) for r in rows], dtype=float)
    booster = T.fit(enc.matrix(rows), y, enc, {"num_leaves": 7, "learning_rate": 0.3, "n_estimators": 10,
                                                 "min_child_samples": 5, "feature_fraction": 1.0, "lambda_l2": 0.0}, "binary")
    T.save(booster, tmp_path / "out" / "v1" / "international_t1.txt")
    manifest = {"version": "v1", "models": {"international_t1": {"file": "v1/international_t1.txt", "encoder": enc.to_json(),
                                                                  "platt": [1.0, 0.0]}}}
    (tmp_path / "out" / "models.json").write_text(json.dumps(manifest))
    store = LocalStore(tmp_path / "lake")
    store.commit({P.MANIFEST: tmp_path / "out" / "models.json",
                  f"{P.MODELS_PREFIX}/v1/international_t1.txt": tmp_path / "out" / "v1" / "international_t1.txt"}, Manifest(), "m")
    got_manifest, models = P.load_models(store, tmp_path / "tmp")
    model, enc2, platt = models["international_t1"]
    assert got_manifest["version"] == "v1" and platt == (1.0, 0.0) and enc2.features == enc.features
    assert np.allclose(T.score(model, enc2.matrix(rows)), T.score(booster, enc.matrix(rows)))


def test_live_relations(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    from lookedup.forecast import predict as P

    h = datetime(2026, 10, 10, 1)
    f = tmp_path / "day.parquet"
    pq.write_table(pa.table({"ts_hour_start": [h, h], "lang": ["en", "fr"], "title": ["A", "B"],
                             "views_desktop": [150, 50], "views_mobile": [0, 10]}), f)
    con = duckdb.connect()
    con.execute("CREATE VIEW _sp AS SELECT 'en' AS lang, 'A' AS title, TIMESTAMP '2026-10-10 01:00' AS ts_hour_start, 40.0 AS baseline_median")
    ev = {"event_id": "E", "qid": 1, "start_hour": h, "lead_lang": "en", "breadth": 2, "event_class": "multi_language"}
    P.live_relations(con, [ev], {1: "death"}, {1: "human"}, {1: {"en": "A", "fr": "B"}}, [f])
    assert con.sql("SELECT lang, views, baseline_median FROM _fviews").fetchall() == [("en", 150, 40.0)]
    assert con.sql("SELECT category FROM _fev").fetchone() == ("death",)
    assert con.sql("SELECT entity_class, n_languages FROM _fdims").fetchone() == ("human", 2)


def test_entity_classes(monkeypatch):
    import json

    import pyarrow as pa

    import lookedup.analytics.entities as E
    from lookedup.forecast import predict as P

    monkeypatch.setattr(E, "fetch_claims", lambda qids, cache: pa.table({"qid": [1, 2], "label_en": ["A", "B"],
        "claims_json": [json.dumps({"P31": [5]}), json.dumps({"P31": []})]}))
    assert P.entity_classes({1, 2}) == {1: "human", 2: "other"}
    assert P.entity_classes(set()) == {}


def test_targets_without_a_model_are_skipped():
    events = [{"event_id": "young", "qid": 1, "start_hour": T0, "lead_lang": "en", "breadth": 2, "event_class": "multi_language"}]
    models = {k: v for k, v in _models().items() if k == "planetary_t3"}
    out = forecast_open(_con(5), events, T0 + timedelta(hours=6), last_hour=T0 + timedelta(hours=5),
                        manifest={"version": "v2"}, models=models)
    assert out == {"young": {"offset_h": 3, "model_version": "v2", "p_planetary": 0.6}}


def test_platt_parameters_are_applied():
    events = [{"event_id": "young", "qid": 1, "start_hour": T0, "lead_lang": "en", "breadth": 2, "event_class": "multi_language"}]
    enc = T.Encoder({"lead_lang": ["en"], "entity_class": ["human"]})
    models = {"international_t3": (Stub(0.6), enc, (1.0, -np.log(1.5)))}                 # odds 1.5 -> 1.0
    out = forecast_open(_con(5), events, T0 + timedelta(hours=6), last_hour=T0 + timedelta(hours=5), manifest={}, models=models)
    assert out["young"]["p_international"] == 0.5 and out["young"]["model_version"] is None


def test_missing_model_files_are_skipped(tmp_path):
    import json

    from lookedup.forecast import predict as P
    from lookedup.store import LocalStore, Manifest

    enc = T.Encoder({"lead_lang": ["en"]}, features=["lead_lang"])
    manifest = {"version": "v1", "models": {"planetary_t1": {"file": "v1/planetary_t1.txt", "encoder": enc.to_json()}}}
    (tmp_path / "models.json").write_text(json.dumps(manifest))
    store = LocalStore(tmp_path / "lake")
    store.commit({P.MANIFEST: tmp_path / "models.json"}, Manifest(), "manifest without its model file")
    got, models = P.load_models(store, tmp_path / "tmp")
    assert got["version"] == "v1" and models == {}


def test_event_past_every_tier_gets_no_probability():
    events = [{"event_id": "wide", "qid": 2, "start_hour": T0, "lead_lang": "en", "breadth": 25, "event_class": "multi_language"}]
    models = {k: v for k, v in _models().items() if not k.startswith("m2_")}
    out = forecast_open(_con(25), events, T0 + timedelta(hours=6), last_hour=T0 + timedelta(hours=5), manifest={}, models=models)
    assert out == {"wide": {"offset_h": 3, "model_version": None}}


def test_attention_left_only_at_three_hours():
    events = [{"event_id": "young", "qid": 1, "start_hour": T0, "lead_lang": "en", "breadth": 2, "event_class": "multi_language"}]
    out = forecast_open(_con(5), events, T0 + timedelta(hours=3), last_hour=T0 + timedelta(hours=2), manifest={}, models=_models())
    young = out["young"]
    assert young["offset_h"] == 1 and young["p_international"] == 0.6
    assert "predicted_excess_24h" not in young and "fade_eta" not in young
