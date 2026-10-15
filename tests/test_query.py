"""Querying the lake with DuckDB, on a small local lake built from the dump sample."""
from __future__ import annotations

from datetime import datetime

import pytest

from conftest import HOURLY_SAMPLE, LANGS
from lookedup import query
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
