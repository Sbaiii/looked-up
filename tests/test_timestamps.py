from datetime import datetime

from lookedup.evaluation.timestamps import infobox_time


def test_infobox_timestamp():
    text = "{{Infobox earthquake\n| timestamp = 2026-08-10 12:34:28\n| local_time = 07:34:28 COT\n}}"
    assert infobox_time(text) == datetime(2026, 8, 10, 12, 34)
    assert infobox_time("| timestamp = 2026-08-10T7:05") == datetime(2026, 8, 10, 7, 5)
    assert infobox_time("{{Infobox person | birth_date = 1950 }}") is None


def _page(content, title="Quake"):
    return {"query": {"pages": [{"title": title, "revisions": [{"slots": {"main": {"content": content}}}]}]}}


def _created(ts, title="Quake"):
    return {"query": {"pages": [{"title": title, "revisions": [{"timestamp": ts}]}]}}


def test_event_time_from_the_infobox(monkeypatch):
    from datetime import date

    import lookedup.evaluation.timestamps as T

    monkeypatch.setattr(T, "_api", lambda params: _page("| timestamp = 2026-08-10 12:34"))
    assert T.event_time("Quake", date(2026, 8, 11)) == {"time": datetime(2026, 8, 10, 12, 34), "source": "infobox_timestamp"}


def test_event_time_falls_back_to_creation(monkeypatch):
    from datetime import date

    import lookedup.evaluation.timestamps as T

    replies = [_page("| timestamp = 2019-01-01 00:00"), _created("2026-08-10T13:05:00Z")]
    monkeypatch.setattr(T, "_api", lambda params: replies.pop(0))
    assert T.event_time("Quake", date(2026, 8, 10)) == {"time": datetime(2026, 8, 10, 13, 5), "source": "article_created"}


def test_no_event_time_for_old_articles_or_missing_pages(monkeypatch):
    from datetime import date

    import lookedup.evaluation.timestamps as T

    replies = [_page("no infobox"), _created("2015-03-01T00:00:00Z")]
    monkeypatch.setattr(T, "_api", lambda params: replies.pop(0))
    assert T.event_time("Quake", date(2026, 8, 10)) is None
    monkeypatch.setattr(T, "_api", lambda params: {"query": {"pages": [{"title": "Nothing", "missing": True}]}})
    assert T.event_time("Nothing", date(2026, 8, 10)) is None


def test_api_call_is_paced(monkeypatch):
    import lookedup.evaluation.timestamps as T

    slept, seen = [], []

    class S:
        def get(self, url, params=None, timeout=None):
            seen.append(params)
            return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: {"query": {}}})()

    monkeypatch.setattr(T, "session", lambda: S())
    monkeypatch.setattr(T.time, "sleep", lambda s: slept.append(s))
    assert T._api({"action": "query"}) == {"query": {}}
    assert slept == [0.35] and seen == [{"action": "query", "format": "json", "formatversion": 2}]


def test_no_event_time_without_a_first_revision(monkeypatch):
    from datetime import date

    import lookedup.evaluation.timestamps as T

    replies = [_page("no infobox"), {"query": {"pages": [{"title": "Quake"}]}}]
    monkeypatch.setattr(T, "_api", lambda params: replies.pop(0))
    assert T.event_time("Quake", date(2026, 8, 10)) is None
