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


LISTING = """<html><body><pre>
<a href="pageviews-20261007-100000.gz">pageviews-20261007-100000.gz</a>          07-Oct-2026 12:14    55123456
<a href="pageviews-20261007-110000.gz">pageviews-20261007-110000.gz</a>          07-Oct-2026 13:20    56000000
<a href="projectviews-20261007-110000">projectviews-20261007-110000</a>          07-Oct-2026 13:20    1000
</pre></body></html>"""


class _Page:
    def __init__(self, status, text=""):
        self.status_code, self.text, self.ok = status, text, status < 400

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_list_month_parses_the_listing(monkeypatch):
    from datetime import datetime

    monkeypatch.setattr(dumps._session, "get", lambda url, timeout=None: _Page(200, LISTING))
    files = dumps.list_month(2026, 10)
    assert [f.name for f in files] == ["pageviews-20261007-100000.gz", "pageviews-20261007-110000.gz"]
    f = files[0]
    assert f.ts_hour_start == datetime(2026, 10, 7, 9) and f.posted == datetime(2026, 10, 7, 12, 14)
    assert f.size == 55123456 and f.url.endswith("/2026/2026-10/pageviews-20261007-100000.gz")
    assert f.lag_minutes == 134
