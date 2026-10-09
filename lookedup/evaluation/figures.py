"""Phase 2 figures (docs/figures/): one message per chart, clean matplotlib defaults."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

INK, MUTED, ACCENT, GRID = "#1f2933", "#7b8794", "#2f6fdf", "#e4e7eb"


def _style(ax, title: str, subtitle: str | None = None) -> None:
    fig = ax.figure
    fig.subplots_adjust(top=0.82)
    fig.text(0.02, 0.965, title, fontsize=13, fontweight="bold", color=INK, va="top", ha="left")
    if subtitle:
        fig.text(0.02, 0.905, subtitle, fontsize=9.5, color=MUTED, va="top", ha="left")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=INK, labelsize=9)
    ax.grid(axis="x" if ax.get_xlim() else "y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def spread_chart(rows: list[tuple[str, int]], label: str, start: str, out: Path) -> None:
    """Hours after the lead language until each language spiked, for one event."""
    rows = sorted(rows, key=lambda r: (r[1], r[0]))
    fig, ax = plt.subplots(figsize=(7, 0.2 * len(rows) + 1.8))
    langs, lags = [r[0] for r in rows], [r[1] for r in rows]
    ax.hlines(range(len(rows)), 0, lags, color=GRID, linewidth=2)
    ax.scatter(lags, range(len(rows)), color=[ACCENT if l == 0 else INK for l in lags], s=36, zorder=3)
    ax.set_yticks(range(len(rows)), langs)
    ax.invert_yaxis()
    ax.set_xlabel("hours after the first language spiked", color=INK)
    ax.set_xticks(range(0, max(lags) + 1))
    ax.tick_params(axis="y", labelsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    _style(ax, f"Attention to {label} reached {len(rows)} languages in {max(lags)} hours",
           f"event start {start} UTC; lead language in blue")
    ax.grid(axis="y", visible=False)
    fig.savefig(out, dpi=160)
    plt.close(fig)


def breadth_histogram(breadths: list[int], out: Path) -> None:
    """How many languages an attention event reaches within 24 h."""
    fig, ax = plt.subplots(figsize=(7, 3.6))
    lo, hi = min(breadths), max(breadths)
    counts = [breadths.count(b) for b in range(lo, hi + 1)]
    ax.bar(range(lo, hi + 1), counts, color=ACCENT, width=0.8)
    ax.set_xlabel("languages spiking within 24 h (breadth)", color=INK)
    ax.set_ylabel("events", color=INK)
    share3 = sum(b <= 4 for b in breadths) / len(breadths)
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    _style(ax, "Most attention events stay within a handful of languages",
           f"{len(breadths):,} events, 16 Jul – 7 Oct 2026; {share3:.0%} reach 3–4 languages")
    ax.grid(axis="x", visible=False)
    fig.savefig(out, dpi=160)
    plt.close(fig)


def recall_vs_threshold(grid_csv: Path, out: Path) -> None:
    """Recall (24 h) against the R3 threshold for each minimum-language setting (6-hour window)."""
    rows = [r for r in csv.DictReader(open(grid_csv)) if r["window_hours"] == "6"]
    fig, ax = plt.subplots(figsize=(7, 3.8))
    best = 0.0
    for n, colour in zip(("2", "3", "5"), (MUTED, ACCENT, INK)):
        sub = sorted((r for r in rows if r["min_languages"] == n), key=lambda r: float(r["r3_threshold"]))
        x = [str(int(float(r["r3_threshold"]))) for r in sub]
        y = [100 * float(r["recall_24h"]) for r in sub]
        best = max(best, *y)
        ax.plot(x, y, marker="o", color=colour, label=f"≥ {n} languages", linewidth=2)
        ax.annotate(f"{y[-1]:.1f} %", (x[-1], y[-1]), textcoords="offset points", xytext=(8, -3), fontsize=8.5, color=colour)
    ax.axhline(70, color=GRID)
    ax.set_ylim(0, 12)
    ax.set_ylabel("recall within 24 h (%)", color=INK)
    ax.set_xlabel("R3 surprise threshold", color=INK)
    ax.legend(frameon=False, fontsize=8.5, loc="upper right")
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    _style(ax, f"Recall stays under {int(best) + 1} % at every threshold",
           "major (date, QID) pairs, 6-hour window; the pre-registered target was 70 % within 6 h")
    fig.savefig(out, dpi=160)
    plt.close(fig)


def lead_language_bars(rows: list[tuple[str, int]], out: Path, top: int = 15) -> None:
    """Which language spikes first."""
    all_total, all_n = sum(r[1] for r in rows), len(rows)
    rows = sorted(rows, key=lambda r: -r[1])[:top]
    fig, ax = plt.subplots(figsize=(7, 0.3 * len(rows) + 1.6))
    ax.barh([r[0] for r in rows], [r[1] for r in rows], color=[ACCENT if i == 0 else MUTED for i in range(len(rows))])
    ax.invert_yaxis()
    ax.set_xlabel("events led", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    _style(ax, f"English leads only {rows[0][1] / all_total:.0%} of events" if rows[0][0] == "en"
           else f"{rows[0][0]} leads the most events", f"top {len(rows)} of {all_n} lead languages, primary configuration")
    ax.grid(axis="y", visible=False)
    fig.savefig(out, dpi=160)
    plt.close(fig)


def deaths_by_languages(rows: list[dict], out: Path) -> None:
    """GT1: share of deaths detected, by how many of our 30 languages have an article (with the 2/3/5 ablation)."""
    buckets = [("5–9", 5, 9), ("10–19", 10, 19), ("20–30", 20, 30)]
    fig, ax = plt.subplots(figsize=(7, 3.8))
    width = 0.26
    for k, (key, colour, label) in enumerate((("detected_n2", MUTED, "≥ 2 languages"), ("detected", ACCENT, "≥ 3 (primary)"),
                                               ("detected_n5", INK, "≥ 5 languages"))):
        ys = []
        for _, lo, hi in buckets:
            sub = [r for r in rows if lo <= int(r["n_languages"]) <= hi]
            ys.append(100 * sum(r[key] == "True" for r in sub) / len(sub))
        xs = [i + (k - 1) * width for i in range(len(buckets))]
        ax.bar(xs, ys, width=width, color=colour, label=label)
        if key == "detected":
            for x, y in zip(xs, ys):
                ax.text(x, y + 1.5, f"{y:.0f} %", ha="center", fontsize=8.5, color=ACCENT)
    ns = [sum(lo <= int(r["n_languages"]) <= hi for r in rows) for _, lo, hi in buckets]
    ax.set_xticks(range(len(buckets)), [f"{b[0]} languages\n(n = {n})" for b, n in zip(buckets, ns)])
    ax.axhline(60, color=GRID)
    ax.set_ylim(0, 100)
    ax.set_ylabel("deaths detected within 24 h (%)", color=INK)
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    _style(ax, "Only widely known deaths draw multi-language attention",
           "GT1: Wikipedia death lists, Jul–Sep 2026; pre-registered target 60 % (grey line)")
    ax.grid(axis="x", visible=False)
    fig.savefig(out, dpi=160)
    plt.close(fig)


def quakes_timeline(rows: list[dict], out: Path) -> None:
    """GT2: every M6+ earthquake by origin time and magnitude, detected within 6 h or not."""
    from datetime import datetime

    fig, ax = plt.subplots(figsize=(7, 3.8))
    for det, colour, label in ((True, ACCENT, "detected within 6 h"), (False, MUTED, "not detected")):
        sub = [r for r in rows if (r["detected"] == "True") == det]
        ax.scatter([datetime.fromisoformat(r["origin"]) for r in sub], [float(r["mag"]) for r in sub],
                   s=[30 + 25 * (float(r["mag"]) - 6) ** 2 * 4 for r in sub], color=colour, label=label, zorder=3,
                   edgecolor="white", linewidth=0.6)
        for r in sub:
            if det:
                ax.annotate(r["place"].split(",")[-1].replace("Earthquake", "").strip()[:20], (datetime.fromisoformat(r["origin"]), float(r["mag"])),
                            textcoords="offset points", xytext=(6, 4), fontsize=7.5, color=ACCENT)
    ax.axhline(6.5, color=GRID)
    ax.set_ylabel("magnitude (USGS)", color=INK)
    ax.legend(frameon=False, fontsize=8.5, loc="upper right")
    fig.autofmt_xdate()
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    big = [r for r in rows if float(r["mag"]) >= 6.5]
    _style(ax, f"{sum(r['detected'] == 'True' for r in big)} of {len(big)} M6.5+ earthquakes became attention events",
           "GT2: USGS M ≥ 6.0, 16 Jul – 7 Oct 2026; detection within 6 h of origin, any target")
    fig.savefig(out, dpi=160)
    plt.close(fig)


def matches_timeline(rows: list[dict], out: Path) -> None:
    """GT3: kick-off vs first spiking hour for the matches inside the scored period."""
    from datetime import datetime

    fig, ax = plt.subplots(figsize=(7, 3.0))
    for i, r in enumerate(rows):
        ko = datetime.fromisoformat(r["kickoff"])
        ax.scatter([0], [i], color=INK, marker="|", s=300, zorder=3)
        if r["start_hour"]:
            d = (datetime.fromisoformat(r["start_hour"]) - ko.replace(minute=0)).total_seconds() / 3600
            ax.scatter([d], [i], color=ACCENT, s=60, zorder=3)
            ax.annotate(f"{d:+.0f} h, {r['breadth']} languages", (d, i), textcoords="offset points", xytext=(8, -3),
                        fontsize=8.5, color=ACCENT)
    ax.set_yticks(range(len(rows)), [r["teams"].replace(" national football team", "") for r in rows], fontsize=8.5)
    ax.set_xlim(-3, 3)
    ax.set_xlabel("hours relative to kick-off (black)", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.78))
    _style(ax, "Both in-window World Cup matches were detected at kick-off",
           "GT3: only 2 of 16 knockout matches fall inside the scored period (from 16 Jul)")
    ax.grid(axis="y", visible=False)
    fig.savefig(out, dpi=160)
    plt.close(fig)


def delay_histogram(values: list[float], out: Path, title: str, subtitle: str, xlabel: str) -> None:
    fig, ax = plt.subplots(figsize=(7, 3.4))
    lo, hi = int(min(values)), int(max(values)) + 1
    ax.hist(values, bins=range(max(lo, -12), min(hi, 13) + 1), color=ACCENT, edgecolor="white")
    ax.axvline(0, color=INK, linewidth=1)
    ax.set_xlabel(xlabel, color=INK)
    ax.set_ylabel("deaths", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.84))
    _style(ax, title, subtitle)
    ax.grid(axis="x", visible=False)
    fig.savefig(out, dpi=160)
    plt.close(fig)
