from datetime import datetime

from lookedup.evaluation.timestamps import infobox_time


def test_infobox_timestamp():
    text = "{{Infobox earthquake\n| timestamp = 2026-08-10 12:34:28\n| local_time = 07:34:28 COT\n}}"
    assert infobox_time(text) == datetime(2026, 8, 10, 12, 34)
    assert infobox_time("| timestamp = 2026-08-10T7:05") == datetime(2026, 8, 10, 7, 5)
    assert infobox_time("{{Infobox person | birth_date = 1950 }}") is None
