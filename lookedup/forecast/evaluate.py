"""Pre-registered Phase 4 backtest (docs/prereg_phase4.md): tuning on validation, one scoring of the test set,
baselines, rolling-origin folds, permutation importance, sensitivity without leak-prone features, figures.

    python -m lookedup.cli forecast-evaluate        # writes docs/analysis/phase4_*.json|csv, docs/figures/phase4_*.png
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import timedelta
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, mean_absolute_error, roc_auc_score

from lookedup import db
from lookedup.forecast import train as T
from lookedup.forecast.features import LEAKY
from lookedup.settings import DATA_DIR, ROOT

log = logging.getLogger(__name__)

OUT = ROOT / "docs" / "analysis"
FIG = ROOT / "docs" / "figures"
PARAMS_FILE = ROOT / "config" / "forecast_params.json"
FOLDS = [("2026-09-10", "2026-09-17"), ("2026-09-17", "2026-09-24"), ("2026-09-24", "2026-10-01"),
         ("2026-10-01", "2026-10-07")]


def load_rows(con) -> list[dict]:
    rel = con.sql("""SELECT s.*, e.label_en, e.breadth AS final_breadth
                     FROM wh.main.fct_event_snapshots s JOIN wh.main.fct_app_events e USING (event_id)""")
    cols = rel.columns
    return [dict(zip(cols, r)) for r in rel.fetchall()]


# ---------------------------------------------------------------- metrics

def calib_slope(y: np.ndarray, p: np.ndarray) -> float:
    if len(set(y)) < 2:
        return float("nan")
    lr = LogisticRegression(C=1e6, max_iter=1000).fit(T.logit(p).reshape(-1, 1), y)
    return float(lr.coef_[0][0])


def calib_curve(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        m = (p >= lo) & ((p < hi) if i < bins - 1 else (p <= hi))
        if m.any():
            out.append({"bin": i, "mean_p": float(p[m].mean()), "observed": float(y[m].mean()), "n": int(m.sum())})
    return out


def lift_top10(y: np.ndarray, s: np.ndarray) -> float:
    k = max(1, int(round(0.1 * len(y))))
    top = np.argsort(-s, kind="stable")[:k]
    base = y.mean()
    return float(y[top].mean() / base) if base > 0 else float("nan")


def m1_metrics(y: np.ndarray, s: np.ndarray, prob: bool = True) -> dict:
    two = len(set(y)) > 1
    out = {"n": int(len(y)), "positives": int(y.sum()),
           "roc_auc": float(roc_auc_score(y, s)) if two else None,
           "pr_auc": float(average_precision_score(y, s)) if two else None,
           "lift_top10": lift_top10(y, s)}
    if prob:
        out |= {"brier": float(brier_score_loss(y, s)), "calibration_slope": calib_slope(y, s)}
    return out


def m2_metrics(y_log: np.ndarray, p_log: np.ndarray, hours: bool = False) -> dict:
    pos = y_log > 0
    out = {"n": int(len(y_log)), "mae_log": float(mean_absolute_error(y_log, p_log)),
           "mape_log": float(np.mean(np.abs(p_log[pos] - y_log[pos]) / y_log[pos])) if pos.any() else None}
    if hours:
        out["median_abs_error_hours"] = float(np.median(np.abs(np.expm1(p_log) - np.expm1(y_log))))
    return out


# ---------------------------------------------------------------- baselines

def sitelinks_logistic(train: list[dict]) -> LogisticRegression:
    X = np.log1p([[r["n_sitelinks"]] for r in train])
    return LogisticRegression(max_iter=1000).fit(X, [r["_y"] for r in train])


def m1_baselines(tr: list[dict], te: list[dict], y_tr: np.ndarray, y_te: np.ndarray) -> dict:
    for r, y in zip(tr, y_tr):
        r["_y"] = y
    base = np.full(len(te), y_tr.mean())
    sl = sitelinks_logistic(tr).predict_proba(np.log1p([[r["n_sitelinks"]] for r in te]))[:, 1]
    rule = np.array([r["breadth_t"] for r in te], dtype=float)
    rule_bin = (rule >= 3).astype(int)
    out = {"base_rate": m1_metrics(y_te, base) | {"roc_auc": 0.5},
           "breadth_rule": m1_metrics(y_te, rule, prob=False),
           "sitelinks_logistic": m1_metrics(y_te, sl)}
    tp = int(((rule_bin == 1) & (y_te == 1)).sum())
    out["breadth_rule"] |= {"rule_precision": tp / max(1, rule_bin.sum()), "rule_recall": tp / max(1, y_te.sum())}
    return out, sl


def decay_ratios(train: list[dict]) -> dict[str, float]:
    by: dict[str, list[float]] = {}
    for r in train:
        if r["excess_hour_t"] > 0:
            by.setdefault(r["category"] or "other", []).append(r["excess_next24"] / r["excess_hour_t"])
    allr = [v for vs in by.values() for v in vs]
    out = {k: float(np.median(v)) for k, v in by.items() if len(v) >= 20}
    out["_all"] = float(np.median(allr)) if allr else 0.0
    return out


def m2_baselines(target: str, tr: list[dict], te: list[dict]) -> dict[str, np.ndarray]:
    if target == "excess_next24":
        ratios = decay_ratios(tr)
        persist = np.log1p([r["excess_hour_t"] * 24 for r in te])
        decay = np.log1p([r["excess_hour_t"] * ratios.get(r["category"] or "other", ratios["_all"]) for r in te])
        return {"persistence": persist, "category_decay": decay}
    med: dict[str, list[float]] = {}
    for r in tr:
        med.setdefault(r["category"] or "other", []).append(r["fade_hours"])
    cat = {k: float(np.median(v)) for k, v in med.items() if len(v) >= 20}
    allm = float(np.median([r["fade_hours"] for r in tr]))
    return {"persistence": np.log1p([min(r["hours_since_peak"] or 0, 48) for r in te]),
            "category_decay": np.log1p([cat.get(r["category"] or "other", allm) for r in te])}


# ---------------------------------------------------------------- pieces

def fit_m1(tr, va, target, params, enc):
    y_tr, y_va = T.labels(tr, target), T.labels(va, target)
    model = T.fit(enc.matrix(tr), y_tr, enc, params, "binary")
    ab = T.platt(T.score(model, enc.matrix(va)), y_va)
    return model, ab


def permutation_importance(model, enc, rows, target, repeats=5, calibrated=None) -> list[dict]:
    rng = np.random.default_rng(T.SEED)
    X = enc.matrix(rows)
    y = T.labels(rows, target)
    m1 = target in T.TARGETS
    metric = (lambda p: average_precision_score(y, p)) if m1 else (lambda p: -mean_absolute_error(y, p))
    base = metric(T.score(model, X))
    out = []
    for j, f in enumerate(enc.features):
        drops = []
        for _ in range(repeats):
            Xp = X.copy()
            Xp[:, j] = rng.permutation(Xp[:, j])
            drops.append(base - metric(T.score(model, Xp)))
        out.append({"feature": f, "importance": float(np.mean(drops)), "std": float(np.std(drops))})
    return sorted(out, key=lambda d: -d["importance"])


def rolling(rows, params_m1, params_m2) -> list[dict]:
    from datetime import datetime
    out = []
    for lo, hi in FOLDS:
        lo_d, hi_d = datetime.fromisoformat(lo), datetime.fromisoformat(hi)
        cal_lo = lo_d - timedelta(days=7)
        tr = [r for r in rows if r["start_hour"] < cal_lo]
        ca = [r for r in rows if cal_lo <= r["start_hour"] < lo_d]
        te = [r for r in rows if lo_d <= r["start_hour"] < hi_d]
        f = {"fold": f"{lo}..{hi}"}
        a, b, c = (T.m1_rows(x, "international", 1) for x in (tr, ca, te))
        enc = T.Encoder.fit(a)
        model, ab = fit_m1(a, b, "international", params_m1, enc)
        p = T.calibrate(T.score(model, enc.matrix(c)), ab)
        f["m1_international_1h"] = m1_metrics(T.labels(c, "international"), p)
        a2, c2 = T.m2_rows(tr + ca, "excess_next24"), T.m2_rows(te, "excess_next24")
        enc2 = T.Encoder.fit(a2)
        m2 = T.fit(enc2.matrix(a2), T.labels(a2, "excess_next24"), enc2, params_m2, "regression")
        y2 = T.labels(c2, "excess_next24")
        f["m2_excess"] = m2_metrics(y2, T.score(m2, enc2.matrix(c2)))
        f["m2_excess_category_decay"] = m2_metrics(y2, m2_baselines("excess_next24", a2, c2)["category_decay"])
        out.append(f)
        log.info("fold %s done", f["fold"])
    return out


# ---------------------------------------------------------------- figures

def plot_calibration(curves: dict[str, list[dict]], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from lookedup.evaluation.figures import ACCENT, INK, MUTED, GRID, _style

    fig, ax = plt.subplots(figsize=(5.6, 5))
    ax.plot([0, 1], [0, 1], color=GRID, lw=1)
    for (name, pts), colour, mk in zip(curves.items(), (ACCENT, MUTED), ("o", "s")):
        ax.plot([p["mean_p"] for p in pts], [p["observed"] for p in pts], marker=mk, color=colour, label=name)
    ax.set_xlabel("predicted probability", color=INK)
    ax.set_ylabel("observed share that went international", color=INK)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    _style(ax, "Calibration on the test set", "Will it go international? Snapshots at t0 + 1 h, 10 bins")
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_importance(imp: list[dict], path: Path, title: str, subtitle: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from lookedup.evaluation.figures import ACCENT, INK, _style

    top = imp[:10][::-1]
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.barh([d["feature"] for d in top], [d["importance"] for d in top], xerr=[d["std"] for d in top], color=ACCENT)
    ax.set_xlabel("drop in validation PR AUC when the feature is shuffled", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    _style(ax, title, subtitle)
    ax.grid(axis="y", visible=False)
    fig.savefig(path, dpi=160)
    plt.close(fig)


# ---------------------------------------------------------------- run

def run() -> dict:
    from lookedup.warehouse import WAREHOUSE_DB

    con = db.connect()
    con.execute(f"ATTACH '{WAREHOUSE_DB}' AS wh (READ_ONLY)")
    rows = load_rows(con)
    sp = T.split(rows)
    res: dict = {"split_sizes": {k: len(v) for k, v in sp.items()}, "m1": {}, "m2": {}}
    chosen: dict = {}
    models: dict = {}
    for target in T.TARGETS:
        for off in T.OFFSETS:
            tr, va, te = (T.m1_rows(sp[k], target, off) for k in ("train", "valid", "test"))
            enc = T.Encoder.fit(tr)
            params, val = T.search(tr, va, target, enc)
            model, ab = fit_m1(tr, va, target, params, enc)
            y_te = T.labels(te, target)
            p_te = T.calibrate(T.score(model, enc.matrix(te)), ab)
            base, sl = m1_baselines(tr, te, T.labels(tr, target), y_te)
            # all snapshots at this offset (reached rows are certain: p = 1), descriptive only
            all_te = [r for r in sp["test"] if r["offset_h"] == off]
            thr = T.TARGETS[target][1]
            p_all = np.array([1.0 if r["breadth_t"] >= thr else 0.0 for r in all_te])
            open_idx = [i for i, r in enumerate(all_te) if r["breadth_t"] < thr]
            p_all[open_idx] = T.calibrate(T.score(model, enc.matrix([all_te[i] for i in open_idx])), ab)
            key = f"{target}_t{off}"
            res["m1"][key] = {"validation_pr_auc": val, "model": m1_metrics(y_te, p_te),
                              "calibration_curve": calib_curve(y_te, p_te), "baselines": base,
                              "sitelinks_calibration_curve": calib_curve(y_te, sl),
                              "all_snapshots_descriptive": m1_metrics(T.labels(all_te, target), p_all)}
            chosen[key] = params
            models[key] = (model, enc, ab, te, p_te)
            log.info("M1 %s: test AUC %.3f PR %.3f", key, res["m1"][key]["model"]["roc_auc"] or 0,
                     res["m1"][key]["model"]["pr_auc"] or 0)
    for target in T.M2_TARGETS:
        tr, va, te = (T.m2_rows(sp[k], target) for k in ("train", "valid", "test"))
        enc = T.Encoder.fit(tr)
        params, val = T.search(tr, va, target, enc)
        model = T.fit(enc.matrix(tr), T.labels(tr, target), enc, params, "regression")
        y_te = T.labels(te, target)
        p_te = T.score(model, enc.matrix(te))
        hours = target == "fade_hours"
        res["m2"][target] = {"validation_mae_log": val, "model": m2_metrics(y_te, p_te, hours),
                             "baselines": {k: m2_metrics(y_te, v, hours) for k, v in m2_baselines(target, tr, te).items()}}
        chosen[f"m2_{target}"] = params
        models[f"m2_{target}"] = (model, enc, None, te, p_te)
        log.info("M2 %s: test MAE %.3f", target, res["m2"][target]["model"]["mae_log"])

    # verdicts
    h = res["m1"]["international_t1"]
    auc, slope = h["model"]["roc_auc"], h["model"]["calibration_slope"]
    res["H6"] = {"roc_auc": auc, "calibration_slope": slope,
                 "verdict": "supported" if auc >= 0.80 and 0.8 <= slope <= 1.2 else "rejected"}
    ratio = h["baselines"]["sitelinks_logistic"]["pr_auc"] / h["model"]["pr_auc"]
    res["H7"] = {"sitelinks_pr_auc": h["baselines"]["sitelinks_logistic"]["pr_auc"], "model_pr_auc": h["model"]["pr_auc"],
                 "ratio": ratio, "verdict": "supported" if ratio >= 0.70 else "rejected"}
    m2e = res["m2"]["excess_next24"]
    gain = 1 - m2e["model"]["mae_log"] / m2e["baselines"]["category_decay"]["mae_log"]
    res["H8"] = {"model_mae_log": m2e["model"]["mae_log"], "category_decay_mae_log": m2e["baselines"]["category_decay"]["mae_log"],
                 "improvement": gain, "verdict": "supported" if gain >= 0.20 else "rejected"}

    # sensitivity without leak-prone features (same parameters)
    tr, va, te = (T.m1_rows(sp[k], "international", 1) for k in ("train", "valid", "test"))
    enc_s = T.Encoder.fit(tr, [f for f in T.FEATURES if f not in LEAKY])
    ms, abs_ = fit_m1(tr, va, "international", chosen["international_t1"], enc_s)
    res["sensitivity_without_sitelinks_and_death"] = m1_metrics(T.labels(te, "international"),
                                                                T.calibrate(T.score(ms, enc_s.matrix(te)), abs_))
    # permutation importance on validation
    model, enc, _, _, _ = models["international_t1"]
    res["importance_international_t1"] = permutation_importance(model, enc, va, "international")
    m2m, m2enc, *_ = models["m2_excess_next24"]
    res["importance_m2_excess"] = permutation_importance(m2m, m2enc, T.m2_rows(sp["valid"], "excess_next24"), "excess_next24")
    res["rolling_folds"] = rolling(rows, chosen["international_t1"], chosen["m2_excess_next24"])

    # five example events (test, international at t0 + 1 h)
    _, _, _, te, p_te = models["international_t1"]
    y_te = T.labels(te, "international")
    order = np.argsort(-p_te)
    pos = [i for i in order if y_te[i] == 1]
    neg = [i for i in order if y_te[i] == 0]
    picks = {"confident hit": pos[0], "false alarm": neg[0], "missed": pos[-1], "median call": order[len(order) // 2]}
    m2m, m2enc, _, te3, p3 = models["m2_excess_next24"]
    big = int(np.argmax([r["excess_next24"] for r in te3]))
    examples = []
    for why, i in picks.items():
        r = te[i]
        examples.append({"why": why, "event_id": r["event_id"], "label": r["label_en"], "snapshot": str(r["snapshot_ts"]),
                         "breadth_t": r["breadth_t"], "n_sitelinks": r["n_sitelinks"], "p_international": round(float(p_te[i]), 3),
                         "final_breadth": r["final_breadth"], "went_international": int(y_te[i])})
    r = te3[big]
    examples.append({"why": "largest attention left", "event_id": r["event_id"], "label": r["label_en"],
                     "snapshot": str(r["snapshot_ts"]), "predicted_excess_24h": round(float(np.expm1(p3[big]))),
                     "actual_excess_24h": round(r["excess_next24"]), "final_breadth": r["final_breadth"]})
    res["examples"] = examples

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "phase4_metrics.json").write_text(json.dumps(res, indent=1, default=str))
    with (OUT / "phase4_examples.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=sorted({k for e in examples for k in e}))
        w.writeheader()
        w.writerows(examples)
    PARAMS_FILE.write_text(json.dumps(chosen, indent=1) + "\n")
    FIG.mkdir(parents=True, exist_ok=True)
    plot_calibration({"model (calibrated)": h["calibration_curve"], "sitelinks only": h["sitelinks_calibration_curve"]},
                     FIG / "phase4_calibration.png")
    plot_importance(res["importance_international_t1"], FIG / "phase4_importance.png",
                    "What the model leans on", "Will it go international at t0 + 1 h? Permutation importance, validation")
    # backtest models (trained on train only) for inspection
    sizes = {}
    for key, (model, enc, ab, *_rest) in models.items():
        sizes[key] = T.save(model, DATA_DIR / "models" / "backtest" / f"{key}.txt")
    res["backtest_model_bytes"] = sizes
    (OUT / "phase4_metrics.json").write_text(json.dumps(res, indent=1, default=str))
    return res
