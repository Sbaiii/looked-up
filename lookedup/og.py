"""Open Graph images (1200x630 PNG) for the web app (ADR 0027), rendered with Pillow from the app's own
data: one per day under data/app/og/YYYY-MM-DD.png, and a default card for the site root.

The hero rule (ADR 0024) and the colour scale (ADR 0025) mirror app/js/select.js and app/js/scale.js.

    python -m lookedup.og --default app/assets/og.png
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from lookedup.settings import ROOT

W, H = 1200, 630
FONT = ROOT / "app" / "assets" / "fonts" / "archivo.woff2"
MONO = ROOT / "app" / "assets" / "fonts" / "plex-mono-500.woff2"
WORLD = ROOT / "app" / "data" / "world-2d.json"
GEO = ROOT / "app" / "data" / "language_geo.json"

PAPER, PAPER2, INK, MUTED, RULE = "#08090b", "#101217", "#edeff2", "#a3abb6", "#1e2127"
ACCENT, PLANETARY, LAND, LAND_LANG = "#6b93ff", "#ffcf5c", "#1a1e26", "#252b36"
RAMP = ("#26345c", "#6b93ff", "#d6e1ff")

# ADR 0024: hero selection
HERO_MIN_EXCESS = 100_000
STRONG_TIERS = {"international", "planetary"}
# ADR 0025: absolute colour scale on per-language peak surprise
SCALE_MIN, SCALE_MAX = 8.0, 5000.0


def rank(events: list[dict]) -> list[dict]:
    """Multi-language events by total excess views, ties broken by breadth."""
    multi = [e for e in events if e.get("class") != "single_language"]
    return sorted(multi, key=lambda e: (-e["excess"], -e["breadth"], e["id"]))


def qualifies(e: dict) -> bool:
    return e["excess"] >= HERO_MIN_EXCESS or e["tier"] in STRONG_TIERS


def pick(events: list[dict], strict: bool = True) -> dict | None:
    """The hero / day event: the top-ranked qualifying event; without ``strict``, the top event anyway."""
    ranked = rank(events)
    good = [e for e in ranked if qualifies(e)]
    return good[0] if good else (None if strict else (ranked[0] if ranked else None))


def scale(surprise: float) -> float:
    """0..1 on a fixed log scale from the spike threshold (8) to 5,000+, the same for every event."""
    if surprise <= SCALE_MIN:
        return 0.0
    return min(1.0, math.log(surprise / SCALE_MIN) / math.log(SCALE_MAX / SCALE_MIN))


def _rgb(h: str) -> tuple[int, int, int]:
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def ramp(x: float) -> tuple[int, int, int]:
    a, b = (RAMP[0], RAMP[1]) if x < 0.5 else (RAMP[1], RAMP[2])
    f = x * 2 if x < 0.5 else (x - 0.5) * 2
    return tuple(round(p + (q - p) * f) for p, q in zip(_rgb(a), _rgb(b)))


def font(size: int, weight: int = 800, mono: bool = False) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(MONO if mono else FONT), size)
    if not mono:
        f.set_variation_by_axes([weight])
    return f


def _polygons(d: str) -> list[list[tuple[float, float]]]:
    out = []
    for ring in d.split("Z"):
        pts = [(float(x), float(y)) for x, y in re.findall(r"[ML](-?[\d.]+),(-?[\d.]+)", ring)]
        if len(pts) > 2:
            out.append(pts)
    return out


def draw_map(img: Image.Image, box: tuple[int, int, int, int], colours: dict[str, tuple[int, int, int]]) -> None:
    world = json.loads(WORLD.read_text())
    lang_countries = {k for keys in json.loads(GEO.read_text())["languages"].values() for k in keys}
    x0, y0, x1, y1 = box
    s = min((x1 - x0) / world["w"], (y1 - y0) / world["h"])
    draw = ImageDraw.Draw(img)
    for c in world["countries"]:
        fill = colours.get(c["k"]) or _rgb(LAND_LANG if c["k"] in lang_countries else LAND)
        for poly in _polygons(c["d"]):
            pts = [(x0 + x * s, y0 + y * s) for x, y in poly if x <= world["w"] + 2]
            if len(pts) > 2:
                draw.polygon(pts, fill=fill, outline=_rgb(PAPER))


def country_colours(event: dict) -> dict[str, tuple[int, int, int]]:
    """Each country takes the max over its languages' scale values (ADR 0023, 0025)."""
    geo = json.loads(GEO.read_text())["languages"]
    best: dict[str, float] = {}
    for r in event.get("langs", []):
        v = scale(r["surprise"])
        for k in geo.get(r["lang"], []):
            best[k] = max(best.get(k, 0.0), v)
    return {k: ramp(v) for k, v in best.items() if v > 0}


def _wrap(draw, text: str, f, width: int, lines: int) -> list[str]:
    words, out, line = text.split(), [], ""
    for w in words:
        trial = f"{line} {w}".strip()
        if draw.textlength(trial, font=f) <= width:
            line = trial
        else:
            out.append(line)
            line = w
    out.append(line)
    if len(out) > lines:
        out = out[:lines]
        while draw.textlength(out[-1] + "…", font=f) > width and " " in out[-1]:
            out[-1] = out[-1].rsplit(" ", 1)[0]
        out[-1] += "…"
    return [l for l in out if l]


def _base() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), _rgb(PAPER))
    draw = ImageDraw.Draw(img)
    for x in range(0, W, 80):                       # the graph-paper motif
        draw.line([(x, 0), (x, H)], fill=_rgb("#111318"))
    for y in range(0, H, 80):
        draw.line([(0, y), (W, y)], fill=_rgb("#111318"))
    draw.ellipse([60, 58, 84, 82], outline=_rgb(ACCENT), width=4)
    draw.ellipse([67, 65, 77, 75], fill=_rgb(ACCENT))
    draw.text((98, 56), "Looked Up", font=font(28, 800), fill=_rgb(INK))
    return img, draw


def within(h: int) -> str:
    return "under an hour" if h == 0 else f"{h} hour" if h == 1 else f"{h} hours"


def render_day(day: date, events: list[dict], out: Path) -> Path:
    img, draw = _base()
    ev = pick(events, strict=False)
    draw.text((60, 120), f"{day:%-d %B %Y}".upper() + " · THE WORLD LOOKED UP", font=font(22, mono=True), fill=_rgb(MUTED))
    if ev:
        label = ev["labels"].get("en") or next(iter(ev["labels"].values()), ev["qid"])
        y = 165
        for line in _wrap(draw, label, font(76, 800), 1080, 2):
            draw.text((60, y), line, font=font(76, 800), fill=_rgb(ACCENT))
            y += 84
        desc = ev.get("desc", {}).get("en")
        if desc:
            draw.text((60, y + 6), desc, font=font(28, 500), fill=_rgb(MUTED))
            y += 44
        n = ev["breadth"]
        draw.text((60, y + 20), f"{n} language{'s' if n != 1 else ''} in {within(ev['spread_h'])}", font=font(44, 750), fill=_rgb(INK))
        draw_map(img, (600, 380, 1150, 600), country_colours(ev))
    else:
        draw.text((60, 170), "A quiet day", font=font(76, 800), fill=_rgb(ACCENT))
        draw_map(img, (600, 380, 1150, 600), {})
    draw.text((60, 560), "sbaiii.github.io/looked-up", font=font(22, mono=True), fill=_rgb(MUTED))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)
    return out


def render_default(out: Path) -> Path:
    img, draw = _base()
    draw.text((60, 120), "30 WIKIPEDIA LANGUAGES · UPDATED HOURLY", font=font(22, mono=True), fill=_rgb(MUTED))
    y = 165
    for line in ("What the world", "looked up, hour", "by hour"):
        draw.text((60, y), line, font=font(80, 800), fill=_rgb(INK))
        y += 88
    geo = json.loads(GEO.read_text())["languages"]
    colours = {k: ramp(0.35 + 0.6 * (i % 7) / 6) for i, keys in enumerate(geo.values()) for k in keys}
    draw_map(img, (600, 380, 1150, 600), colours)
    draw.text((60, 560), "sbaiii.github.io/looked-up", font=font(22, mono=True), fill=_rgb(MUTED))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--default", type=Path, help="write the default card to this path")
    p.add_argument("--day-file", type=Path, help="render one app day file (JSON) ...")
    p.add_argument("--out", type=Path, help="... to this PNG")
    a = p.parse_args()
    if a.default:
        print(render_default(a.default))
    if a.day_file:
        d = json.loads(a.day_file.read_text())
        print(render_day(date.fromisoformat(d["date"]), d["events"], a.out))


if __name__ == "__main__":
    main()
