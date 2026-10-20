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


def test_claims_from_sparql(monkeypatch):
    import json as _json

    from lookedup.analytics import entities as E

    W = "http://www.wikidata.org"
    answers = [
        [{"item": {"value": f"{W}/entity/Q1"}, "p": {"value": f"{W}/prop/direct/P31"}, "v": {"value": f"{W}/entity/Q5"}},
         {"item": {"value": f"{W}/entity/Q1"}, "p": {"value": f"{W}/prop/direct/P570"}, "v": {"value": "2026-08-17T00:00:00Z"}},
         {"item": {"value": f"{W}/entity/Q1"}, "p": {"value": f"{W}/prop/direct/P17"}, "v": {"value": "not an item"}}],
        [{"item": {"value": f"{W}/entity/Q1"}, "l": {"value": "Someone"}}],
    ]
    monkeypatch.setattr(E, "_sparql", lambda q: answers.pop(0))
    monkeypatch.setattr(E.time, "sleep", lambda s: None)
    rows = E.fetch_claims_sparql([1, 2])
    by = {r["qid"]: r for r in rows}
    assert by[1]["label_en"] == "Someone" and by[2]["label_en"] is None
    c = _json.loads(by[1]["claims_json"])
    assert c["P31"] == [5] and c["P570"] == ["2026-08-17"] and c["P17"] == []


def test_fetch_claims_uses_the_cache(tmp_path, monkeypatch):
    from lookedup.analytics import entities as E

    asked = []
    monkeypatch.setattr(E, "fetch_claims_sparql", lambda todo: asked.append(list(todo)) or
                        [{"qid": q, "label_en": f"L{q}", "claims_json": "{}"} for q in todo])
    cache = tmp_path / "claims.parquet"
    E.fetch_claims([3, 1], cache)
    t = E.fetch_claims([1, 2, 3], cache)
    assert asked == [[1, 3], [2]]
    assert sorted(t["qid"].to_pylist()) == [1, 2, 3]
    E.fetch_claims([1, 2], cache)
    assert asked[-1] == []                                             # everything already cached


def test_fetch_claims_falls_back_to_the_api(tmp_path, monkeypatch):
    import requests

    from lookedup.analytics import entities as E

    def down(todo):
        raise requests.ConnectionError("query service down")

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"entities": {"Q7": {"labels": {"en": {"value": "Seven"}},
                                        "claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"numeric-id": 5}}}}]}},
                                 "Q8": {"missing": ""}}}

    monkeypatch.setattr(E, "fetch_claims_sparql", down)
    monkeypatch.setattr(E, "session", lambda: type("S", (), {"get": lambda self, *a, **k: R()})())
    monkeypatch.setattr(E.time, "sleep", lambda s: None)
    t = E.fetch_claims([7, 8], tmp_path / "claims.parquet")
    assert t["qid"].to_pylist() == [7] and t["label_en"].to_pylist() == ["Seven"]


def test_gender_values():
    from lookedup.analytics.entities import FEMALE, MALE, gender_of

    assert gender_of([]) is None
    assert gender_of(sorted(FEMALE)) == "female" and gender_of([min(MALE)]) == "male"
    assert gender_of([min(FEMALE), min(MALE)]) == "other" and gender_of([48270]) == "other"


def test_descriptions_and_gender_from_sparql(monkeypatch):
    import json as _json

    from lookedup.analytics import entities as E

    W = "http://www.wikidata.org/entity/"
    answers = [
        [{"item": {"value": W + "Q1"}, "d": {"value": "actrice américaine", "xml:lang": "fr"}},
         {"item": {"value": W + "Q1"}, "d": {"value": "American actress", "xml:lang": "en"}}],
        [{"item": {"value": W + "Q1"}, "g": {"value": W + "Q6581072"}}],
    ]
    monkeypatch.setattr(E, "_sparql", lambda q: answers.pop(0))
    monkeypatch.setattr(E.time, "sleep", lambda s: None)
    rows = {r["qid"]: r for r in E.fetch_text_sparql([1, 2], ["en", "fr"])}
    assert _json.loads(rows[1]["descriptions_json"]) == {"fr": "actrice américaine", "en": "American actress"}
    assert rows[1]["gender"] == "female" and rows[2]["gender"] is None and rows[2]["descriptions_json"] == "{}"


def test_sparql_retries_then_raises(monkeypatch):
    import pytest
    import requests

    from lookedup.analytics import entities as E

    attempts = []

    class S:
        def post(self, *a, **k):
            attempts.append(1)
            raise requests.ConnectionError("down")

    monkeypatch.setattr(E, "session", lambda: S())
    monkeypatch.setattr(E.time, "sleep", lambda s: None)
    with pytest.raises(requests.ConnectionError):
        E._sparql("SELECT 1")
    assert len(attempts) == 5


def test_unparsable_death_dates_are_ignored():
    assert not died_near({"P570": ["unknown", "2026-13-01"]}, date(2026, 8, 17), CFG)
    assert died_near({"P570": ["unknown", "2026-08-16"]}, date(2026, 8, 17), CFG)


def test_sparql_recovers_from_bad_json(monkeypatch):
    from lookedup.analytics import entities as E

    rows = [{"item": {"value": "http://www.wikidata.org/entity/Q5"}}]
    answers = [None, {"results": {"bindings": rows}}]
    sleeps = []

    class R:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            if self.data is None:
                raise ValueError("HTML error page")
            return self.data

    monkeypatch.setattr(E, "session", lambda: type("S", (), {"post": lambda self, *a, **k: R(answers.pop(0))})())
    monkeypatch.setattr(E.time, "sleep", sleeps.append)
    assert E._sparql("SELECT ?item WHERE {}") == rows and sleeps == [5]


def test_api_fallback_retries_a_batch(tmp_path, monkeypatch):
    import requests

    from lookedup.analytics import entities as E

    replies = [requests.ConnectionError("blip"),
               {"entities": {"Q9": {"labels": {}, "claims": {}}}}]
    sleeps = []

    class R:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    def get(self, *a, **k):
        x = replies.pop(0)
        if isinstance(x, Exception):
            raise x
        return R(x)

    monkeypatch.setattr(E, "fetch_claims_sparql", lambda todo: (_ for _ in ()).throw(requests.ConnectionError("down")))
    monkeypatch.setattr(E, "session", lambda: type("S", (), {"get": get})())
    monkeypatch.setattr(E.time, "sleep", sleeps.append)
    t = E.fetch_claims([9], tmp_path / "claims.parquet")
    assert t["qid"].to_pylist() == [9] and t["label_en"].to_pylist() == [None] and sleeps[0] == 3


def test_fetch_text_all_cached(tmp_path, monkeypatch):
    from lookedup.analytics import entities as E

    monkeypatch.setattr(E, "fetch_text_sparql", lambda qids, langs: [{"qid": q, "descriptions_json": "{}", "gender": None} for q in qids])
    cache = tmp_path / "text.parquet"
    E.fetch_text([4, 5], cache, ["en"])
    monkeypatch.setattr(E, "fetch_text_sparql", lambda qids, langs: (_ for _ in ()).throw(AssertionError("no query expected")))
    assert sorted(E.fetch_text({5, 4}, cache, ["en"])["qid"].to_pylist()) == [4, 5]


def test_dates_keep_only_time_values():
    from lookedup.analytics.entities import _dates

    claims = {"P570": [{"mainsnak": {"datavalue": {"value": {"time": "+2026-08-28T00:00:00Z"}}}},
                       {"mainsnak": {"snaktype": "somevalue"}},
                       {"mainsnak": {"datavalue": {"value": "2026"}}}]}
    assert _dates(claims, "P570") == ["+2026-08-28T00:00:00Z"] and _dates(claims, "P569") == []


def test_api_fallback_gives_up(tmp_path, monkeypatch):
    import pytest
    import requests

    from lookedup.analytics import entities as E

    tries = []

    def get(self, *a, **k):
        tries.append(1)
        raise requests.ConnectionError("API down too")

    monkeypatch.setattr(E, "fetch_claims_sparql", lambda todo: (_ for _ in ()).throw(requests.ConnectionError("down")))
    monkeypatch.setattr(E, "session", lambda: type("S", (), {"get": get})())
    monkeypatch.setattr(E.time, "sleep", lambda s: None)
    with pytest.raises(requests.ConnectionError, match="API down too"):
        E.fetch_claims([9], tmp_path / "claims.parquet")
    assert len(tries) == 5 and not (tmp_path / "claims.parquet").exists()
