"""Run the pre-registered Phase 2 evaluation and write docs/analysis/ outputs.

    python -m lookedup.cli evaluate            # metrics, ablations, H2, H4, delays, review lists
    python -m lookedup.cli evaluate --audit-sample   # write the blind H3 sheet (before labelling)
    python -m lookedup.cli evaluate --audit-score    # score H3 once docs/analysis/h3_labels.csv is committed
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

from lookedup.analytics.config import load
from lookedup.evaluation import audit, metrics
from lookedup.settings import DATA_DIR, ROOT
from lookedup.warehouse import WAREHOUSE_DB

log = logging.getLogger(__name__)

OUT = ROOT / "docs" / "analysis"
CURRENT_EVENTS = DATA_DIR / "eval" / "current_events.parquet"
CLAIMS = DATA_DIR / "warehouse" / "entity_claims.parquet"


def _csv(path: Path, rows: list[dict] | list[tuple], header: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        if rows and isinstance(rows[0], dict):
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        else:
            w = csv.writer(f, lineterminator="\n")
            if header:
                w.writerow(header)
            w.writerows(rows)


def evaluate() -> dict:
    cfg = load()
    ctx = metrics.open_context(WAREHOUSE_DB, CURRENT_EVENTS, cfg)
    con = ctx.con
    con.execute("CREATE TABLE primary_events AS SELECT * FROM wh.main.fct_attention_events")
    ev = "primary_events"
    res: dict = {"config": {"r3_threshold": cfg.spike.r3_threshold, "min_languages": cfg.event.min_languages,
                            "window_hours": cfg.event.window_hours}}
    res["events_eval_period"] = metrics.event_count(ctx, ev)
    res["events_total"] = con.execute(f"SELECT count(*) FROM {ev}").fetchone()[0]
    res["major_pairs"] = con.execute("SELECT count(*) FROM majors").fetchone()[0]
    res["h1"] = {"recall_6h": metrics.recall(ctx, ev, 6), "recall_24h": metrics.recall(ctx, ev, 24)}
    r6 = res["h1"]["recall_6h"]["recall"]
    res["h1"]["verdict"] = "supported" if r6 is not None and r6 >= 0.70 else "rejected"
    res["precision"] = metrics.precision_proxy(ctx, ev)
    _csv(OUT / "recall_by_section.csv", metrics.recall_by_section(ctx, ev, 24),
         ["section", "pairs", "detected_24h", "recall_24h"])
    leads = metrics.lead_counts(ctx, ev)
    res["lead_counts"] = leads
    _csv(OUT / "lead_counts.csv", leads, ["lead_lang", "events"])
    # sensitivity analyses (ADR 0013)
    s1 = metrics.variant_events(ctx, cfg.event, "events_s1", spikes="spikes_s1")
    res["s1_no_flat_rule"] = {"events": metrics.event_count(ctx, s1), "recall_6h": metrics.recall(ctx, s1, 6),
                              "recall_24h": metrics.recall(ctx, s1, 24), "precision": metrics.precision_proxy(ctx, s1)}
    res["s2_story_headers"] = {"pairs": con.execute("SELECT count(*) FROM majors_s2").fetchone()[0],
                               "recall_6h": metrics.recall(ctx, ev, 6, "majors_s2"),
                               "recall_24h": metrics.recall(ctx, ev, 24, "majors_s2")}
    res["h4"] = metrics.h4_spread(ctx, ev)
    res["h2"] = metrics.h2_lead_language(ctx, ev, CLAIMS)
    grid = metrics.ablation_grid(ctx)
    _csv(OUT / "ablation_grid.csv", grid)
    res["ablation_winner"] = next(g for g in grid if g["winner"])
    delays = metrics.detection_delays(ctx, ev)
    _csv(OUT / "detection_delays.csv", delays.pop("rows") or [{"note": "no timestamps"}])
    res["delays"] = delays
    # largest events not in the portal (±2 days) -> manual review sheet
    k = cfg.raw["evaluation"]["precision_window_days"]
    rows = con.execute(f"""
        SELECT e.event_id, e.qid, e.label_en, e.category, e.start_hour, e.lead_lang, e.breadth,
               round(e.peak_intensity, 1) AS peak_intensity, e.excess_views, e.languages
        FROM {ev} e
        WHERE e.start_hour::DATE BETWEEN DATE '{cfg.eval_start}' AND DATE '{cfg.period_end}'
          AND NOT EXISTS (SELECT 1 FROM portal_qids p WHERE p.qid = e.qid
                          AND p.date BETWEEN e.start_hour::DATE - {k} AND e.start_hour::DATE + {k})
        ORDER BY e.excess_views DESC LIMIT {cfg.raw['evaluation']['manual_review_top_n']}""").fetchall()
    cols = ["event_id", "qid", "label_en", "category", "start_hour", "lead_lang", "breadth", "peak_intensity",
            "excess_views", "languages"]
    _csv(OUT / "nonportal_top30.csv", [dict(zip(cols, r)) | {"languages": " ".join(r[-1])} for r in rows])
    (OUT / "phase2_metrics.json").write_text(json.dumps(res, indent=1, default=metrics.to_jsonable))
    return res


def audit_sample() -> int:
    cfg = load()
    ctx = metrics.open_context(WAREHOUSE_DB, CURRENT_EVENTS, cfg)
    return audit.sample(ctx.con, cfg, OUT / "h3_sample.csv")


def audit_score() -> dict:
    cfg = load()
    ctx = metrics.open_context(WAREHOUSE_DB, CURRENT_EVENTS, cfg)
    res = audit.score(ctx.con, cfg, OUT / "h3_sample.csv", OUT / "h3_labels.csv")
    _csv(OUT / "h3_audit.csv", res.pop("rows"))
    (OUT / "h3_results.json").write_text(json.dumps(res, indent=1))
    return res
