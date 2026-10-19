"""Production scoring against the batch warehouse on held-out hours (ADR 0014), on a tiny synthetic lake."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import duckdb
import pyarrow as pa
import pytest

from lookedup.evaluation import agreement
from lookedup.store import LocalStore, write_hours
from lookedup.transform import SCHEMA

D = date(2026, 9, 2)


def _hour(ts, rows):
    return pa.table({"ts_hour_start": [ts] * len(rows), "lang": [r[0] for r in rows], "title": [r[1] for r in rows],
                     "views_desktop": [r[2] for r in rows], "views_mobile": [r[3] for r in rows]}).cast(SCHEMA)


@pytest.fixture
def lake(tmp_path):
    """28 quiet days of background traffic, then a burst on the scored day."""
    store = LocalStore(tmp_path / "lake")
    tables = {}
    quiet = [("en", "Background", 20, 30), ("en", "Quake_X", 5, 5), ("es", "Sismo_X", 4, 4)]
    for k in range(1, 29):
        for h in range(24):
            ts = datetime.combine(D - timedelta(days=k), datetime.min.time()) + timedelta(hours=h)
            tables[ts] = (_hour(ts, quiet), "hourly_dump")
    burst = {9: [("es", "Sismo_X", 50, 900)], 10: [("en", "Quake_X", 100, 1500), ("es", "Sismo_X", 40, 700)]}
    for h in range(12):
        ts = datetime.combine(D, datetime.min.time()) + timedelta(hours=h)
        tables[ts] = (_hour(ts, burst.get(h, quiet)), "hourly_dump")
    write_hours(store, tables, "seed")
    return store.root


def _warehouse(path, spikes):
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE int_spikes (lang VARCHAR, title VARCHAR, ts_hour_start TIMESTAMP, day DATE, hour_of_day INT, is_spike BOOLEAN)")
    for lang, title, h, flag in spikes:
        ts = datetime.combine(D, datetime.min.time()) + timedelta(hours=h)
        con.execute("INSERT INTO int_spikes VALUES (?, ?, ?, ?, ?, ?)", [lang, title, ts, D, h, flag])
    con.close()
    return path



def test_counts_and_shares_against_the_batch(lake, tmp_path):
    wh = _warehouse(tmp_path / "w.duckdb", [("en", "Quake_X", 10, True), ("en", "Nope", 10, True), ("es", "Sismo_X", 11, False)])
    res = agreement.production_vs_batch(wh, D, [9, 10, 11], lake_dir=lake)
    assert res["day"] == "2026-09-02" and res["hours"] == [9, 10, 11]
    assert (res["batch_spikes"], res["production_spikes"], res["both"]) == (2, 3, 1)   # Sismo_X at 9 and 10, Quake_X at 10
    assert res["share_of_batch_reproduced"] == 0.5 and res["share_of_production_in_batch"] == pytest.approx(1 / 3)
    assert res["baseline_slots"] == 48                                                 # 2 candidate titles x 24 hours
