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
