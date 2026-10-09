"""Phase 2 figures (docs/figures/): one message per chart, clean matplotlib defaults."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

INK, MUTED, ACCENT, GRID = "#1f2933", "#7b8794", "#2f6fdf", "#e4e7eb"


def _style(ax, title: str, subtitle: str | None = None) -> None:
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color=INK, pad=22 if subtitle else 10)
    if subtitle:
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9.5, color=MUTED, va="bottom")
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
    fig, ax = plt.subplots(figsize=(7, 0.32 * len(rows) + 1.6))
    langs, lags = [r[0] for r in rows], [r[1] for r in rows]
    ax.hlines(range(len(rows)), 0, lags, color=GRID, linewidth=2)
    ax.scatter(lags, range(len(rows)), color=[ACCENT if l == 0 else INK for l in lags], s=36, zorder=3)
    ax.set_yticks(range(len(rows)), langs)
    ax.invert_yaxis()
    ax.set_xlabel("hours after the first language spiked", color=INK)
    _style(ax, f"How attention to {label} spread across languages", f"event start {start} UTC; lead language in blue")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
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
    _style(ax, "Most attention events stay within a handful of languages",
           f"{len(breadths):,} events, 16 Jul – 7 Oct 2026; {share3:.0%} reach 3–4 languages")
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def recall_vs_threshold(grid_csv: Path, out: Path) -> None:
    """Recall (24 h) and precision proxy against the R3 threshold, primary window and languages."""
    rows = [r for r in csv.DictReader(open(grid_csv)) if r["window_hours"] == "6"]
    fig, ax = plt.subplots(figsize=(7, 3.8))
    for n, colour in zip(("2", "3", "5"), (MUTED, ACCENT, INK)):
        sub = sorted((r for r in rows if r["min_languages"] == n), key=lambda r: float(r["r3_threshold"]))
        x = [float(r["r3_threshold"]) for r in sub]
        ax.plot(x, [float(r["recall_24h"]) for r in sub], marker="o", color=colour, label=f"recall, ≥{n} languages")
        ax.plot(x, [float(r["precision_proxy"]) for r in sub], marker="s", linestyle="--", color=colour,
                label=f"precision proxy, ≥{n} languages")
    ax.set_xlabel("R3 surprise threshold", color=INK)
    ax.set_ylim(0, 1)
    ax.set_xticks([6, 8, 12])
    ax.legend(frameon=False, fontsize=8, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.22))
    _style(ax, "Stricter thresholds trade recall for precision", "6-hour window; recall within 24 h of the portal date")
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def lead_language_bars(rows: list[tuple[str, int]], out: Path, top: int = 15) -> None:
    """Which language spikes first."""
    rows = sorted(rows, key=lambda r: -r[1])[:top]
    total = sum(r[1] for r in rows)
    fig, ax = plt.subplots(figsize=(7, 0.3 * len(rows) + 1.6))
    ax.barh([r[0] for r in rows], [r[1] for r in rows], color=[ACCENT if i == 0 else MUTED for i in range(len(rows))])
    ax.invert_yaxis()
    ax.set_xlabel("events led", color=INK)
    _style(ax, f"English leads {rows[0][1] / total:.0%} of events" if rows[0][0] == "en"
           else f"{rows[0][0]} leads the most events", f"top {len(rows)} lead languages, primary configuration")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)
