from __future__ import annotations

import bz2
import gzip
import shutil
from datetime import date, datetime

import pytest

from conftest import HOURLY_SAMPLE, LANGS, PVC_SAMPLE
from lookedup import backfill, dumps
from lookedup.store import LocalStore, Manifest

DAY = date(2026, 9, 13)


@pytest.fixture
def fake_dumps(monkeypatch, tmp_path, article_filter):
    pvc = tmp_path / "pvc.bz2"
    pvc.write_bytes(bz2.compress(PVC_SAMPLE.read_bytes()))
    hourly = tmp_path / "hourly.gz"
    with open(HOURLY_SAMPLE, "rb") as s, gzip.open(hourly, "wb") as d:
        shutil.copyfileobj(s, d)
    calls = []

    def download(url, dest, retries=8):
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pvc if url.endswith(".bz2") else hourly, dest)
        return dest

    monkeypatch.setattr(dumps, "download", download)
    monkeypatch.setattr(backfill, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(backfill, "active_codes", lambda: LANGS)
    monkeypatch.setattr(backfill, "article_filter", lambda: article_filter)
    return calls


def test_day_range():
    assert backfill.day_range(date(2026, 7, 9), date(2026, 7, 11)) == [date(2026, 7, 11), date(2026, 7, 10),
                                                                       date(2026, 7, 9)]
    assert len(backfill.day_range(date(2026, 7, 9), date(2026, 10, 6))) == 90


def test_backfill_resumes_and_never_overwrites_hourly(fake_dumps, tmp_path):
    store = LocalStore(tmp_path / "lake")
    # the hourly job already ingested 14:00 for that day
    m = Manifest()
    m.add(datetime(2026, 9, 13, 14), rows=1, source="hourly_dump")
    store.commit({}, m, "seed")

    assert backfill.backfill(store, DAY, DAY) == 23
    manifest = store.read_manifest()
    assert len(manifest.hours) == 24
    assert manifest.hours["2026-09-13T14:00:00Z"]["source"] == "hourly_dump"
    assert manifest.hours["2026-09-13T15:00:00Z"]["source"] == "pageview_complete"
    assert not list((tmp_path / "raw").rglob("*.bz2"))     # raw dumps are transient

    downloads = len(fake_dumps)
    assert backfill.backfill(store, DAY, DAY) == 0           # re-run: nothing to do, no download
    assert len(fake_dumps) == downloads


def test_validate_matches_hourly_path(fake_dumps, tmp_path):
    store = LocalStore(tmp_path / "lake")
    backfill.backfill(store, DAY, DAY)
    # only 14:00 has a matching hourly fixture; make it the only pageview_complete hour
    m = store.read_manifest()
    m.hours = {k: v for k, v in m.hours.items() if k == "2026-09-13T14:00:00Z"}
    (tmp_path / "lake" / "data" / "manifest.json").write_text(m.to_json())
    [res] = backfill.validate(store, n=3, seed=1)
    assert res["identical"] and res["stored_rows"] > 100
