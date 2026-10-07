"""Regenerate the test fixtures from real dumps (needs the raw files locally; not run in CI).

Writes two plain-text excerpts that cover the SAME (lang, title) set for 2026-09-13 14:00 UTC:
  * pageviews-20260913-150000.sample  - 2,000 lines of the hourly dump (file named after hour END)
  * pageviews-20260913-user.sample    - the matching pageview_complete lines (all hours of the day)
so tests can check that both ingestion paths give identical rows.

Usage: .venv/bin/python tests/fixtures/make_fixtures.py
"""

from __future__ import annotations

import bz2
import gzip
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
HOURLY = RAW / "pageviews" / "pageviews-20260913-150000.gz"
PVC = RAW / "pageview_complete" / "pageviews-20260913-user.bz2"
OUT = Path(__file__).resolve().parent
LANGS = ["en", "fr", "de", "ja", "ar", "es"]
N = 2000

random.seed(13)
lines = gzip.open(HOURLY, "rt", encoding="utf-8", errors="replace").read().splitlines()
by_key: dict[tuple[str, str], list[int]] = {}
for i, ln in enumerate(lines):
    parts = ln.split(" ")
    if len(parts) == 4:
        by_key.setdefault((parts[0], parts[1]), []).append(i)

chosen: set[int] = set()


def take(pred, k):
    idx = [i for i, ln in enumerate(lines) if pred(ln)]
    chosen.update(random.sample(idx, min(k, len(idx))))


for lang in LANGS:
    # popular titles present on desktop AND mobile (tests summing into two columns)
    both = [(int(lines[i].split(" ")[2]), t) for (p, t), (i, *_) in by_key.items()
            if p == lang and (lang + ".m", t) in by_key]
    for _, t in sorted(both, reverse=True)[:60]:
        chosen.update(by_key[(lang, t)] + by_key[(lang + ".m", t)])
    take(lambda ln, l=lang: ln.startswith((f"{l} ", f"{l}.m ")) and ":" in ln.split(" ")[1], 25)
    take(lambda ln, l=lang: ln.startswith((f"{l} ", f"{l}.m ")), 80)
take(lambda ln: " - " in ln[:12], 10)                                  # the "-" title
take(lambda ln: ln.split(" ")[1:2] and "%" in ln.split(" ")[1], 40)    # percent signs
take(lambda ln: ln.startswith(("commons.m ", "en.d ", "de.b ", "meta.m ", "www.wd ", "en.m.d ")), 120)
for t in ("Main_Page", "Wikipédia:Accueil_principal", "Wikipedia:Hauptseite", "メインページ"):
    for p in ("en", "en.m", "fr", "fr.m", "de", "de.m", "ja", "ja.m"):
        chosen.update(by_key.get((p, t), []))


def siblings(i: int) -> list[int]:
    """The line plus its other-access twin (en <-> en.m), so each Wikipedia title is complete."""
    p, t = lines[i].split(" ")[:2]
    base = p[:-2] if p.endswith(".m") else p
    if base not in LANGS:
        return [i]
    return by_key.get((base, t), []) + by_key.get((base + ".m", t), [])


chosen = {j for i in chosen for j in siblings(i)}
rest = [i for i, ln in enumerate(lines) if ln.split(" ")[0] in LANGS]
while len(chosen) < N:
    chosen.update(siblings(random.choice(rest)))
others = sorted(i for i in chosen if lines[i].split(" ")[0].removesuffix(".m") not in LANGS)
while len(chosen) > N:  # trim with non-Wikipedia lines, which have no twin
    chosen.discard(others.pop())
sample = [lines[i] for i in sorted(chosen)]
assert len(sample) == N, len(sample)
(OUT / "pageviews-20260913-150000.sample").write_text("\n".join(sample) + "\n", encoding="utf-8")

wanted = set()
for ln in sample:
    p, t = ln.split(" ")[:2]
    lang = p.split(".")[0]
    if t != "-":  # "-" has one pvc row per page id (500k+); it is filtered on both paths anyway
        wanted.add((f"{lang}.wikipedia", t))
pvc_lines = []
with bz2.open(PVC, "rt", encoding="utf-8", errors="replace") as f:
    for ln in f:
        parts = ln.split(" ", 2)
        if len(parts) >= 2 and (parts[0], parts[1]) in wanted:
            pvc_lines.append(ln.rstrip("\n"))
(OUT / "pageviews-20260913-user.sample").write_text("\n".join(pvc_lines) + "\n", encoding="utf-8")
print(len(sample), "hourly lines;", len(pvc_lines), "pageview_complete lines")
