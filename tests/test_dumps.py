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


def test_list_month_missing(monkeypatch):
    monkeypatch.setattr(dumps._session, "get", lambda url, timeout=None: _Page(404))
    assert dumps.list_month(2030, 1) == []


def test_available_hours_filters_the_range(monkeypatch):
    from datetime import datetime

    monkeypatch.setattr(dumps._session, "get", lambda url, timeout=None: _Page(200, LISTING))
    got = dumps.available_hours(datetime(2026, 10, 7, 10), datetime(2026, 10, 7, 12))
    assert list(got) == [datetime(2026, 10, 7, 10)]


class _Stream(_Resp):
    def __init__(self, status, body, length=None):
        super().__init__()
        self.status_code, self.body = status, body
        self.headers = {"Content-Length": str(len(body) if length is None else length)}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def iter_content(self, n):
        yield self.body


def test_download_resumes_a_part_file(tmp_path, monkeypatch):
    dest = tmp_path / "f.gz"
    (tmp_path / "f.gz.part").write_bytes(b"hello ")
    seen = []

    def get(url, stream=True, timeout=None, headers=None):
        seen.append(headers)
        return _Stream(206, b"world")

    monkeypatch.setattr(dumps._session, "get", get)
    assert dumps.download("https://x/f.gz", dest) == dest
    assert dest.read_bytes() == b"hello world" and seen == [{"Range": "bytes=6-"}]
    assert not (tmp_path / "f.gz.part").exists()


def test_download_restarts_when_range_is_ignored(tmp_path, monkeypatch):
    dest = tmp_path / "f.gz"
    (tmp_path / "f.gz.part").write_bytes(b"stale")
    monkeypatch.setattr(dumps._session, "get", lambda url, stream=True, timeout=None, headers=None: _Stream(200, b"fresh body"))
    dumps.download("https://x/f.gz", dest)
    assert dest.read_bytes() == b"fresh body"


def test_download_skips_an_existing_file(tmp_path, monkeypatch):
    dest = tmp_path / "f.gz"
    dest.write_bytes(b"done")
    monkeypatch.setattr(dumps._session, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no request")))
    assert dumps.download("https://x/f.gz", dest) == dest and dest.read_bytes() == b"done"


def test_rest_hourly_total(monkeypatch):
    from datetime import datetime

    class R:
        def __init__(self, ok, items):
            self.ok, self.items = ok, items

        def json(self):
            return {"items": self.items}

    replies = [R(False, []), R(True, []), R(True, [{"views": 12345}])]
    urls = []
    monkeypatch.setattr(dumps._session, "get", lambda url, timeout=None: urls.append(url) or replies.pop(0))
    h = datetime(2026, 10, 7, 9)
    assert dumps.rest_hourly_total("en.wikipedia", h) is None
    assert dumps.rest_hourly_total("en.wikipedia", h) is None
    assert dumps.rest_hourly_total("en.wikipedia", h) == 12345
    assert urls[0].endswith("/aggregate/en.wikipedia/all-access/user/hourly/2026100709/2026100709")


def test_download_416_finishes_the_part_file(tmp_path, monkeypatch):
    (tmp_path / "f.gz.part").write_bytes(b"all of it")
    monkeypatch.setattr(dumps._session, "get", lambda url, stream=True, timeout=None, headers=None: _Stream(416, b""))
    assert dumps.download("https://x/f.gz", tmp_path / "f.gz").read_bytes() == b"all of it"


def test_download_gives_up_after_retries(tmp_path, monkeypatch):
    import pytest
    import requests

    calls = []

    def get(*a, **k):
        calls.append(1)
        raise requests.ConnectionError("reset")

    monkeypatch.setattr(dumps._session, "get", get)
    monkeypatch.setattr(dumps.time, "sleep", lambda s: None)
    with pytest.raises(requests.ConnectionError):
        dumps.download("https://x/f.gz", tmp_path / "f.gz", retries=3)
    assert len(calls) == 3 and not (tmp_path / "f.gz").exists()


def test_download_resumes_after_a_cut(tmp_path, monkeypatch):
    seen = []
    replies = [_Stream(200, b"hello ", length=11), _Stream(206, b"world")]

    def get(url, stream=True, timeout=None, headers=None):
        seen.append(headers)
        return replies.pop(0)

    monkeypatch.setattr(dumps._session, "get", get)
    assert dumps.download("https://x/f.gz", tmp_path / "f.gz").read_bytes() == b"hello world"
    assert seen == [{}, {"Range": "bytes=6-"}]
