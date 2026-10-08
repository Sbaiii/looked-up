from __future__ import annotations

import time

from lookedup import dumps


class _Sock:
    def __init__(self):
        self.shut = False

    def shutdown(self, how):
        self.shut = True


class _Resp:
    def __init__(self):
        self.raw = type("Raw", (), {})()
        self.raw.connection = type("Conn", (), {})()
        self.raw.connection.sock = _Sock()
        self.closed = False

    def close(self):
        self.closed = True


def test_watchdog_kills_a_stalled_connection():
    r = _Resp()
    w = dumps._Watchdog(r, min_bps=1000, window=0.2, interval=0.05)
    w.start()
    w.join(timeout=2)
    assert w.stalled and r.raw.connection.sock.shut and r.closed


def test_watchdog_leaves_a_healthy_connection_alone():
    r = _Resp()
    w = dumps._Watchdog(r, min_bps=1000, window=0.2, interval=0.05)
    w.start()
    t_end = time.monotonic() + 0.5
    while time.monotonic() < t_end:
        w.add(10_000)
        time.sleep(0.02)
    w.stop()
    w.join(timeout=2)
    assert not w.stalled and not r.closed
