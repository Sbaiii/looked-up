"""The Phase 2 evaluation runner: its CSV writer and how evaluate() wires the metrics into its outputs."""

from __future__ import annotations

import csv
import json

import duckdb
import pytest

from lookedup.evaluation import run


def _read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def test_csv_writes_dicts_under_their_keys(tmp_path):
    out = tmp_path / "sub" / "a.csv"
    run._csv(out, [{"lang": "en", "n": 3}, {"lang": "fr", "n": 1}])
    assert _read(out) == [["lang", "n"], ["en", "3"], ["fr", "1"]]
