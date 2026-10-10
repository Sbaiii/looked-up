from __future__ import annotations

from datetime import date

from lookedup.analytics.config import load
from lookedup.analytics.entities import classify, died_near, is_generic, parse_entity

CFG = load()


def test_parse_entity_keeps_ids_and_death_dates():
    e = {"claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"numeric-id": 5}}}}],
                    "P570": [{"mainsnak": {"datavalue": {"value": {"time": "+2026-08-28T00:00:00Z"}}}}],
                    "P106": [{"mainsnak": {"snaktype": "novalue"}}]}}
    c = parse_entity(e)
    assert c["P31"] == [5] and c["P570"] == ["2026-08-28"] and c["P106"] == []


def test_classify_priority_and_humans():
    assert classify({"P31": [7944]}, CFG) == "disaster"                       # earthquake
    assert classify({"P31": [5], "P106": [10833314]}, CFG) == "sports"        # tennis player
    assert classify({"P31": [5], "P106": [33999]}, CFG) == "entertainment"    # actor
    assert classify({"P31": [5], "P106": [82955]}, CFG) == "human"            # politician: no class
    assert classify({"P31": [11424, 515]}, CFG) == "entertainment"            # film wins over city
    assert classify({"P31": [123456789]}, CFG) == "other"


def test_generic_and_death_window():
    assert is_generic({"P31": [3624078]}, CFG)
    c = {"P570": ["2026-08-28"]}
    assert died_near(c, date(2026, 8, 28), CFG) and died_near(c, date(2026, 9, 4), CFG)
    assert died_near(c, date(2026, 8, 27), CFG)          # event one day before the recorded date
    assert not died_near(c, date(2026, 9, 6), CFG) and not died_near({}, date(2026, 8, 28), CFG)


def test_gender_from_p21():
    from lookedup.analytics.entities import gender_of
    assert gender_of([6581072]) == "female" and gender_of([1052281]) == "female"
    assert gender_of([6581097]) == "male"
    assert gender_of([48270]) == "other"           # non-binary
    assert gender_of([6581072, 48270]) == "other"
    assert gender_of([]) is None


def test_fetch_text_caches_and_fetches_only_new(tmp_path, monkeypatch):
    from lookedup.analytics import entities
    calls = []

    def fake(qids, langs):
        calls.append(list(qids))
        return [{"qid": q, "descriptions_json": '{"en": "x"}', "gender": None} for q in qids]

    monkeypatch.setattr(entities, "fetch_text_sparql", fake)
    cache = tmp_path / "text.parquet"
    assert entities.fetch_text([1, 2], cache, ["en"]).num_rows == 2
    assert entities.fetch_text([2, 3], cache, ["en"]).num_rows == 3
    assert calls == [[1, 2], [3]]
