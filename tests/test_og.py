from __future__ import annotations

from datetime import date

from PIL import Image

from lookedup import og


def _e(i, excess, breadth, tier="noticed", cls="multi_language", langs=()):
    return {"id": f"Q{i}@x", "qid": f"Q{i}", "excess": excess, "breadth": breadth, "tier": tier, "class": cls,
            "spread_h": 1, "labels": {"en": f"Item {i}"}, "langs": [{"lang": l, "surprise": s} for l, s in langs]}


def test_hero_rule_ranks_by_excess_then_breadth_and_requires_strength():
    weak = _e(1, 13_000, 4)                          # the v1 "Zodiac" case
    assert og.pick([weak]) is None
    assert og.pick([weak], strict=False) is weak
    intl = _e(2, 50_000, 6, tier="international")
    big = _e(3, 150_000, 2)
    assert og.pick([weak, intl, big]) is big          # most excess views wins
    tie = _e(4, 150_000, 3)
    assert og.pick([big, tie]) is tie                 # equal excess: wider breadth wins
    assert og.pick([_e(5, 9e6, 2, cls="single_language"), weak]) is None   # single-language never leads


def test_colour_scale_is_absolute_and_log():
    assert og.scale(8) == 0 and og.scale(5000) == 1 and og.scale(50_000) == 1
    assert 0.25 < og.scale(50) < 0.35 and 0.6 < og.scale(500) < 0.7


def test_render_day_png(tmp_path):
    ev = _e(1, 2e6, 29, "planetary", langs=[("en", 4000), ("fr", 30)])
    out = og.render_day(date(2026, 8, 25), [ev], tmp_path / "og.png")
    img = Image.open(out)
    assert img.size == (1200, 630)
    colours = og.country_colours(ev)
    assert colours["840"] != colours["250"]          # USA (en, strong) vs France (fr, faint)
