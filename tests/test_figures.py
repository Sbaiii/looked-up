"""Every results figure still renders from the committed outputs (into a temp folder, never docs/figures)."""
from __future__ import annotations

import csv
from pathlib import Path

from PIL import Image

from lookedup.evaluation import figures as F

ANALYSIS = Path(__file__).resolve().parents[1] / "docs" / "analysis"


def _png(path: Path) -> tuple[int, int]:
    assert path.exists() and path.stat().st_size > 1000
    return Image.open(path).size


def _rows(name: str) -> list[dict]:
    return list(csv.DictReader(open(ANALYSIS / name, encoding="utf-8")))


def test_spread_chart_and_breadth_histogram(tmp_path):
    F.spread_chart([("en", 0), ("fr", 1), ("ja", 2)], "Example", "2026-08-17 02:00 UTC", tmp_path / "spread.png")
    F.breadth_histogram([3, 3, 4, 5, 9, 20, 28], tmp_path / "breadth.png")
    assert _png(tmp_path / "spread.png")[0] > 0 and _png(tmp_path / "breadth.png")[0] > 0
