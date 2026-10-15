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


def test_recall_and_lead_language_charts(tmp_path):
    F.recall_vs_threshold(ANALYSIS / "ablation_grid.csv", tmp_path / "recall.png")
    leads = [(r["lead_lang"], int(r["events"])) for r in _rows("lead_counts.csv")]
    F.lead_language_bars(leads, tmp_path / "leads.png")
    _png(tmp_path / "recall.png")
    _png(tmp_path / "leads.png")


def test_phase2b_charts(tmp_path):
    F.deaths_by_languages(_rows("phase2b_gt1_deaths.csv"), tmp_path / "deaths.png")
    F.quakes_timeline(_rows("phase2b_gt2_earthquakes.csv"), tmp_path / "quakes.png")
    F.matches_timeline(_rows("phase2b_gt3_matches.csv"), tmp_path / "matches.png")
    for name in ("deaths", "quakes", "matches"):
        _png(tmp_path / f"{name}.png")


def test_delay_histogram(tmp_path):
    F.delay_histogram([-2, -1, -1, 0, 0, 1, 3, 25], tmp_path / "delay.png", "Delay", "from the announcement", "hours")
    _png(tmp_path / "delay.png")


def test_forecast_charts(tmp_path):
    import json

    from lookedup.forecast import evaluate as E

    m = json.loads((ANALYSIS / "phase4_metrics.json").read_text())["m1"]["international_t1"]
    E.plot_calibration({"model": m["calibration_curve"], "fame only": m["sitelinks_calibration_curve"]}, tmp_path / "cal.png")
    imp = [{"feature": f"f{i}", "importance": 0.1 / (i + 1), "std": 0.01} for i in range(12)]
    E.plot_importance(imp, tmp_path / "imp.png", "Importance", "drop in PR AUC")
    _png(tmp_path / "cal.png")
    _png(tmp_path / "imp.png")


def test_lead_time_histogram(tmp_path, monkeypatch):
    from lookedup import live_analysis as LA

    monkeypatch.setattr(LA, "FIG", tmp_path)
    LA.plot_leads([], None)
    assert not (tmp_path / "phase5_lead_time.png").exists()
    LA.plot_leads([-300, -106, -60, -45, 90, 2000], -75.5)
    _png(tmp_path / "phase5_lead_time.png")


def test_default_social_card(tmp_path):
    from lookedup import og

    out = og.render_default(tmp_path / "card.png")
    assert _png(Path(out)) == (og.W, og.H) == (1200, 630)
