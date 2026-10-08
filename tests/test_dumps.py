from __future__ import annotations

import pytest

from lookedup import dumps


def test_stall_watch_aborts_trickling_connections(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(dumps.time, "monotonic", lambda: clock[0])
    w = dumps._StallWatch(min_bps=1000, window=60)
    clock[0] = 61
    w.update(120_000)            # ~2 kB/s: healthy, window resets
    clock[0] = 122
    with pytest.raises(dumps._Stalled):
        w.update(100)            # ~2 B/s over the next window: abort and resume
