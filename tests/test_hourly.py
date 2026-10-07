from __future__ import annotations

import gzip
import shutil
from datetime import datetime, timedelta

import pytest

from conftest import HOURLY_SAMPLE, LANGS
from lookedup import dumps, hourly
from lookedup.store import LocalStore, Manifest

NOW = datetime(2026, 10, 7, 12, 45)


@pytest.fixture
def fake_server(monkeypatch, tmp_path):
    """Every hour up to 2 h ago is published; downloads return the fixture dump."""
    gz = tmp_path / "fixture.gz"
    with open(HOURLY_SAMPLE, "rb") as src, gzip.open(gz, "wb") as dst:
        shutil.copyfileobj(src, dst)
    published_until = NOW - timedelta(hours=2)

    def available_hours(start, end):
        out, ts = {}, start
        while ts < end:
            if ts + timedelta(hours=1) <= published_until:
                out[ts] = dumps.HourlyFile(name=dumps.file_name(ts), url=dumps.file_url(ts), ts_hour_start=ts,
                                           posted=ts + timedelta(hours=3), size=gz.stat().st_size)
            ts += timedelta(hours=1)
        return out

    def download(url, dest, retries=8):
        shutil.copyfile(gz, dest)
        return dest

    monkeypatch.setattr(dumps, "available_hours", available_hours)
    monkeypatch.setattr(dumps, "download", download)


def test_plan_newest_first_capped(fake_server):
    todo, unpublished = hourly.plan(Manifest(), NOW, window_hours=72, max_hours=6)
    starts = [f.ts_hour_start for f in todo]
    assert len(starts) == 6
    assert starts == sorted(starts, reverse=True)
    assert starts[0] == datetime(2026, 10, 7, 9)            # 10:00-11:00 not yet published
    assert unpublished == [datetime(2026, 10, 7, 10), datetime(2026, 10, 7, 11)]


def test_run_is_idempotent_and_self_healing(fake_server, tmp_path, article_filter):
    store = LocalStore(tmp_path / "lake")
    kw = dict(now=NOW, langs=LANGS, filt=article_filter, window_hours=8, max_hours=6)
    assert hourly.run(store, **kw) == 6        # 8 expected, 2 unpublished -> 6 ingested
    assert hourly.run(store, **kw) == 0        # nothing new: no duplicates, no work
    m = store.read_manifest()
    assert len(m.hours) == 6
    assert {e["source"] for e in m.hours.values()} == {"hourly_dump"}

    # an hour lost from the lake is detected and re-ingested on the next run
    lost = datetime(2026, 10, 7, 5)
    m.hours.pop(f"{lost:%Y-%m-%dT%H:00:00Z}")
    (tmp_path / "lake" / "data" / "manifest.json").write_text(m.to_json())
    assert hourly.run(store, **kw) == 1
    assert lost in store.read_manifest().present()


def test_hf_upload_failure_is_loud(fake_server, tmp_path, article_filter):
    class Broken(LocalStore):
        def commit(self, files, entries, message):
            raise RuntimeError("upload failed")

    with pytest.raises(RuntimeError, match="upload failed"):
        hourly.run(Broken(tmp_path / "lake"), now=NOW, langs=LANGS, filt=article_filter, window_hours=3)
