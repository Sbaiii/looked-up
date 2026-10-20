"""The README scorecard quotes the committed results: each number must match docs/analysis/."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _row(hyp: str) -> str:
    """The scorecard row of ``hyp`` (e.g. "H1"), as text."""
    return next(l for l in README.splitlines() if l.startswith(f"| **{hyp}**"))


def _metrics(name: str) -> dict:
    return json.loads((ROOT / "docs" / "analysis" / name).read_text(encoding="utf-8"))


def _pct(x: float) -> str:
    return f"{100 * x:.1f} %"


def test_phase2_rows():
    m = _metrics("phase2_metrics.json")
    r6, h2, h4 = m["h1"]["recall_6h"], m["h2"], m["h4"]
    assert f"{_pct(r6['recall'])} ({r6['detected']:,} / {r6['pairs']:,})" in _row("H1")
    assert f"{_pct(h2['share'])} ({h2['lead_is_official']} / {h2['geolocatable']})" in _row("H2")
    assert f"{h4['median_a']} h vs {h4['median_b']} h" in _row("H4")
    assert f"English leads only {_pct(h2['base_rate_lead_en'])} of events" in README


def test_h3_row():
    h = _metrics("h3_results.json")
    assert f"{h['non_events_flagged']} / {h['non_events']}, under the 20 needed" in _row("H3")
