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
