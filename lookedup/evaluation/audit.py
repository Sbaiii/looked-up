"""H3 audit (prereg §4): blind labelling of anomalies found with the automation filter OFF.

1. ``sample``: pool = (lang, title, day) units with an article-hour passing the primary spike
   rule ignoring automation; keep the top 1,000 by max surprise; draw 100 (seed 20261008).
   Writes docs/analysis/h3_sample.csv: title, language, day and the TOTAL hourly views of the
   day and the 3 days before. No desktop/mobile split, no filter verdict (blind).
2. The labeller fills docs/analysis/h3_labels.csv (unit_id, label, note), committed first.
3. ``score``: joins the labels with the filter's verdicts and computes the H3 metrics.
"""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

LABELS = ("event", "non_event", "unsure")


def sample(con, cfg, out: Path) -> int:
    ev = cfg.raw["evaluation"]
    r3 = cfg.spike.r3_threshold
    units = con.execute(f"""
        SELECT lang, title, day, max(surprise) AS max_surprise
        FROM wh.main.int_spikes
        WHERE surprise >= {r3} AND day BETWEEN DATE '{cfg.eval_start}' AND DATE '{cfg.period_end}'
        GROUP BY ALL ORDER BY max_surprise DESC, lang, title, day LIMIT {ev['h3_pool_size']}""").fetchall()
    picks = random.Random(ev["h3_seed"]).sample(units, min(ev["h3_sample_size"], len(units)))
    rows = []
    for i, (lang, title, day, _) in enumerate(sorted(picks, key=lambda u: (u[0], u[1], u[2])), 1):
        lo = day - timedelta(days=3)
        series = dict(con.execute("""SELECT ts_hour_start, views FROM wh.main.stg_hourly
            WHERE lang = ? AND title = ? AND day BETWEEN ? AND ?""", [lang, title, lo, day]).fetchall())
        start = datetime(lo.year, lo.month, lo.day)
        vals = [series.get(start + timedelta(hours=k), 0) for k in range(96)]
        rows.append({"unit_id": f"u{i:03d}", "lang": lang, "title": title, "day": day.isoformat(),
                     "views_by_hour_d-3_to_d": " ".join(str(v) for v in vals)})
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def score(con, cfg, sample_csv: Path, labels_csv: Path) -> dict:
    s = {r["unit_id"]: r for r in csv.DictReader(open(sample_csv, encoding="utf-8"))}
    labels = {r["unit_id"]: r["label"] for r in csv.DictReader(open(labels_csv, encoding="utf-8"))}
    assert set(labels) == set(s), "every sampled unit needs a label"
    assert set(labels.values()) <= set(LABELS), set(labels.values())
    flagged = {}
    for uid, r in s.items():
        f = con.execute("""SELECT is_automated, is_low_mobile, is_flat FROM wh.main.int_automation_flags
            WHERE lang = ? AND title = ? AND day = ?""", [r["lang"], r["title"], r["day"]]).fetchone()
        flagged[uid] = {"is_automated": bool(f and f[0]), "is_low_mobile": bool(f and f[1]), "is_flat": bool(f and f[2])}
    non = [u for u, l in labels.items() if l == "non_event"]
    evs = [u for u, l in labels.items() if l == "event"]
    min_non = cfg.raw["evaluation"]["h3_min_non_events"]
    share = sum(flagged[u]["is_automated"] for u in non) / len(non) if non else None
    verdict = ("inconclusive (fewer than 20 non-events)" if len(non) < min_non
               else "supported" if share >= 0.90 else "rejected")
    return {
        "labels": {l: sum(v == l for v in labels.values()) for l in LABELS},
        "non_events_flagged": sum(flagged[u]["is_automated"] for u in non), "non_events": len(non),
        "share_non_events_flagged": share,
        "events_wrongly_flagged": sum(flagged[u]["is_automated"] for u in evs), "events": len(evs),
        "share_events_wrongly_flagged": sum(flagged[u]["is_automated"] for u in evs) / len(evs) if evs else None,
        "by_rule": {k: sum(flagged[u][k] for u in non) for k in ("is_low_mobile", "is_flat")},
        "by_rule_events": {k: sum(flagged[u][k] for u in evs) for k in ("is_low_mobile", "is_flat")},
        "verdict": verdict,
        "rows": [{**s[u], "label": labels[u], **flagged[u]} for u in sorted(s)],
    }
