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


def test_h3_row():
    h = _metrics("h3_results.json")
    assert f"{h['non_events_flagged']} / {h['non_events']}, under the 20 needed" in _row("H3")


def test_phase2b_rows():
    b = _metrics("phase2b_metrics.json")
    g1, g2, g3 = b["gt1"], b["gt2"], b["gt3"]
    assert f"{_pct(g1['recall'])} ({g1['detected']} / {g1['n']})" in _row("H1b-1")
    assert f"{g2['m65_plus']['detected']} / {g2['m65_plus']['n']}" in _row("H1b-2")
    assert f"{g3['detected']} / {g3['n']}, under the 5 needed" in _row("H1b-3")
    assert f"{g2['h2b']['lead_is_country_language']} / {g2['h2b']['qualifying']}, under the 5 needed" in _row("H2b")
    assert f"{g2['h5_delay']['median']:.0f} h from {g2['h5_delay']['n']} quakes" in _row("H5")


def test_phase4_rows():
    m = _metrics("phase4_metrics.json")
    assert f"AUC {m['H6']['roc_auc']:.3f}, slope {m['H6']['calibration_slope']:.2f}" in _row("H6")
    assert f"| {100 * m['H7']['ratio']:.0f} % |" in _row("H7")
    assert f"{100 * m['H8']['improvement']:.0f} % lower" in _row("H8")


def test_phase5_row():
    h9 = _metrics("phase5_metrics.json")["H9"]
    assert h9["median_lead_minutes"] < 0                                  # readers first
    assert f"readers first, by a median {-h9['median_lead_minutes']:.0f} min" in _row("H9")


def test_verdicts_match():
    m2, b, m4 = _metrics("phase2_metrics.json"), _metrics("phase2b_metrics.json"), _metrics("phase4_metrics.json")
    verdicts = {"H1": m2["h1"]["verdict"], "H2": m2["h2"]["verdict"], "H3": _metrics("h3_results.json")["verdict"],
                "H4": m2["h4"]["verdict"], "H1b-1": b["gt1"]["verdict_h1b_1"], "H1b-2": b["gt2"]["verdict_h1b_2"],
                "H1b-3": b["gt3"]["verdict_h1b_3"], "H2b": b["gt2"]["verdict_h2b"], "H5": b["gt2"]["verdict_h5"],
                "H6": m4["H6"]["verdict"], "H7": m4["H7"]["verdict"], "H8": m4["H8"]["verdict"],
                "H9": _metrics("phase5_metrics.json")["H9"]["verdict"]}
    for hyp, v in verdicts.items():
        shown = re.search(r"\| (\w+) \|$", _row(hyp)).group(1)
        assert v.startswith(shown), (hyp, shown, v)


def test_headline_counts_the_table():
    from collections import Counter

    rows = [l for l in README.splitlines() if re.match(r"\| \*\*H\d", l)]
    counts = Counter(re.search(r"\| (\w+) \|$", l).group(1) for l in rows)
    m = re.search(r"(\d+) pre-registered hypotheses: \*\*(\d+) supported, (\d+) rejected, (\d+) inconclusive\*\*", README)
    assert [int(g) for g in m.groups()] == [len(rows), counts["supported"], counts["rejected"], counts["inconclusive"]]


def test_nonportal_claim_matches_the_review():
    import csv

    with open(ROOT / "docs" / "analysis" / "nonportal_review.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    real = sum(r["review"] == "real" for r in rows)
    assert f"{real} of the {len(rows)} largest events the English Current events portal never linked are" in README.replace("\n", " ")


def test_english_lead_share():
    h2 = _metrics("phase2_metrics.json")["h2"]
    assert 0 < h2["base_rate_lead_en"] < 0.5                               # "only": English leads a minority of events
    assert f"English leads only {_pct(h2['base_rate_lead_en'])} of events" in README


def _doc(name: str) -> str:
    return (ROOT / "docs" / "analysis" / name).read_text(encoding="utf-8")


def test_phase2_results_page():
    r6 = _metrics("phase2_metrics.json")["h1"]["recall_6h"]
    assert f"**{_pct(r6['recall'])}** ({r6['detected']:,} / {r6['pairs']:,})" in _doc("phase2_results.md")


def test_phase2b_results_page():
    g1 = _metrics("phase2b_metrics.json")["gt1"]
    page = _doc("phase2b_results.md")
    assert f"**{_pct(g1['recall'])}** ({g1['detected']} / {g1['n']})" in page
    assert f"{g1['out_of_window']} are out of window" in page and f"leaving **{g1['n']} scored**" in page
