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
