"""Querying the lake with DuckDB, on a small local lake built from the dump sample."""
from __future__ import annotations

from datetime import datetime

import pytest
from conftest import HOURLY_SAMPLE, LANGS

from lookedup import db, query
from lookedup.store import LocalStore, write_hours
from lookedup.transform import hourly_dump_to_table

H14 = datetime(2026, 9, 13, 14)


@pytest.fixture
def lake(tmp_path, monkeypatch, article_filter):
    root = tmp_path / "lake"
    table = hourly_dump_to_table(HOURLY_SAMPLE, H14, LANGS, article_filter)
    write_hours(LocalStore(root), {H14: (table, "hourly_dump")}, "test")
    monkeypatch.setattr(query, "LOCAL_LAKE_DIR", root)
    return table


def test_lake_root(monkeypatch, tmp_path):
    monkeypatch.delenv("LOOKEDUP_LOCAL_LAKE", raising=False)
    monkeypatch.setattr(query, "LOCAL_LAKE_DIR", tmp_path)
    assert query.lake_root() == f"hf://datasets/{query.HF_REPO_ID}"
    assert query.lake_root(local=True) == str(tmp_path)
    monkeypatch.setenv("LOOKEDUP_LOCAL_LAKE", "1")
    assert query.lake_root() == str(tmp_path)


def test_top_on_a_local_lake(lake):
    rows = query.top("en", H14, n=5, local=True).fetchall()
    assert 0 < len(rows) <= 5
    views = [r[3] for r in rows]
    assert views == sorted(views, reverse=True)
    assert all(r[3] == r[1] + r[2] for r in rows)                     # views = desktop + mobile
    assert all(0 <= r[4] <= 100 for r in rows)                         # mobile share in percent


def test_top_quotes_the_language(lake):
    assert query.top("en' OR '1'='1", H14, local=True).fetchall() == []


def test_connect_views(lake, tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    sl = query.LOCAL_LAKE_DIR / query.SITELINKS_PATH
    sl.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"lang": ["en"], "title": ["Lisbon"], "qid": [597]}), sl)
    con = query.connect(local=True)
    assert db.one(con, "SELECT count(*) FROM hourly")[0] == lake.num_rows
    assert db.one(con, "SELECT qid FROM sitelinks WHERE title = 'Lisbon'")[0] == 597


class _Con:
    def __init__(self):
        self.sql = []

    def execute(self, q):
        self.sql.append(q)


def test_hub_connection_loads_httpfs_and_the_token(monkeypatch):
    con = _Con()
    monkeypatch.setattr(query.db, "connect", lambda: con)
    monkeypatch.setenv("HF_TOKEN", "hf_abc")
    assert query._base("hf://datasets/user/repo") is con
    assert con.sql == ["INSTALL httpfs; LOAD httpfs;", "CREATE SECRET hf (TYPE huggingface, TOKEN 'hf_abc')"]


def test_hub_without_token_and_local_without_httpfs(monkeypatch, tmp_path):
    cons = []
    monkeypatch.setattr(query.db, "connect", lambda: cons.append(_Con()) or cons[-1])
    monkeypatch.delenv("HF_TOKEN", raising=False)
    query._base("hf://datasets/user/repo")
    query._base(str(tmp_path))
    assert cons[0].sql == ["INSTALL httpfs; LOAD httpfs;"] and cons[1].sql == []
