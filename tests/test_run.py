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


def test_csv_writes_tuples_under_a_header(tmp_path):
    run._csv(tmp_path / "b.csv", [("en", 3)], ["lead_lang", "events"])
    run._csv(tmp_path / "c.csv", [], ["lead_lang", "events"])
    run._csv(tmp_path / "d.csv", [("en", 3)])
    assert _read(tmp_path / "b.csv") == [["lead_lang", "events"], ["en", "3"]]
    assert _read(tmp_path / "c.csv") == [["lead_lang", "events"]]                 # empty rows still get the header
    assert _read(tmp_path / "d.csv") == [["en", "3"]]
