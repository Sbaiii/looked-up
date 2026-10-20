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


def test_ramp_hits_its_stops_and_stays_in_range():
    assert og.ramp(0.0) == og._rgb(og.RAMP[0])
    assert og.ramp(0.5) == og._rgb(og.RAMP[1])
    assert og.ramp(1.0) == og._rgb(og.RAMP[2])
    for x in (0.1, 0.3, 0.7, 0.9):
        assert all(0 <= c <= 255 for c in og.ramp(x))


def test_card_qualifies_on_excess_or_a_strong_tier():
    assert og.qualifies({"excess": og.HERO_MIN_EXCESS, "tier": "noticed"})
    assert og.qualifies({"excess": 10, "tier": "international"})
    assert og.qualifies({"excess": 10, "tier": "planetary"})
    assert not og.qualifies({"excess": og.HERO_MIN_EXCESS - 1, "tier": "noticed"})


def test_spread_phrase():
    assert og.within(0) == "under an hour"
    assert og.within(1) == "1 hour"
    assert og.within(7) == "7 hours"


def test_title_wrap_respects_width_and_line_count():
    img, draw = og._base()
    f = og.font(76, 800)
    lines = og._wrap(draw, "A very long title that cannot possibly fit on a single line of the card", f, 600, 2)
    assert 1 < len(lines) <= 2
    assert all(draw.textlength(l, font=f) <= 600 for l in lines[:-1])
    assert img.size == (og.W, og.H)


def test_quiet_day_card(tmp_path):
    out = og.render_day(date(2026, 8, 18), [], tmp_path / "quiet.png")
    assert Image.open(out).size == (og.W, og.H)


def test_long_title_gets_an_ellipsis():
    _img, draw = og._base()
    f = og.font(76, 800)
    lines = og._wrap(draw, " ".join(["word"] * 40), f, 500, 2)
    assert len(lines) == 2 and lines[-1].endswith("…")
    assert draw.textlength(lines[-1], font=f) <= 500


def test_command_line_renders_a_day_file(tmp_path, monkeypatch, capsys):
    import json
    import sys

    day = tmp_path / "2026-08-17.json"
    day.write_text(json.dumps({"date": "2026-08-17", "events": [_e(1, 2_000_000, 12, "international", langs=[("en", 900)])]}))
    monkeypatch.setattr(sys, "argv", ["og", "--day-file", str(day), "--out", str(tmp_path / "card.png"),
                                      "--default", str(tmp_path / "default.png")])
    og.main()
    assert (tmp_path / "card.png").exists() and (tmp_path / "default.png").exists()
    assert "card.png" in capsys.readouterr().out


def test_an_overlong_first_word_keeps_both_lines():
    _img, draw = og._base()
    f = og.font(76, 800)
    lines = og._wrap(draw, "Antidisestablishmentarianism " * 12, f, 520, 2)
    assert lines == ["Antidisestablishmentarianism", "Antidisestablishmentarianism…"]


def test_ellipsis_line_fits_the_width():
    _img, draw = og._base()
    f = og.font(76, 800)
    for text in ("ab cd " * 60, "Wikipedia readers everywhere " * 8, "Mm Mmm " * 30):
        lines = og._wrap(draw, text, f, 520, 2)
        assert len(lines) == 2 and lines[-1].endswith("…")
        assert draw.textlength(lines[-1], font=f) <= 520


def test_command_line_default_only_or_nothing(tmp_path, monkeypatch, capsys):
    import sys

    monkeypatch.setattr(sys, "argv", ["og", "--default", str(tmp_path / "default.png")])
    og.main()
    assert (tmp_path / "default.png").exists() and capsys.readouterr().out.strip().endswith("default.png")
    monkeypatch.setattr(sys, "argv", ["og"])
    og.main()
    assert capsys.readouterr().out == "" and sorted(p.name for p in tmp_path.iterdir()) == ["default.png"]


def test_draw_map_skips_rings_past_the_edge(tmp_path, monkeypatch):
    import json

    world = {"w": 100, "h": 50, "countries": [{"k": "A", "d": "M10,10L30,10L30,30Z"},
                                              {"k": "B", "d": "M150,10L160,10L160,20Z M80,5L98,5L98,20Z"}]}
    (tmp_path / "world.json").write_text(json.dumps(world))
    monkeypatch.setattr(og, "WORLD", tmp_path / "world.json")
    img, _ = og._base()
    og.draw_map(img, (0, 0, 100, 50), {"A": (255, 0, 0), "B": (0, 0, 255)})
    assert img.getpixel((26, 13)) == (255, 0, 0) and img.getpixel((95, 8)) == (0, 0, 255)   # B's far ring is dropped
    assert og._polygons("M0,0L1,1Z M0,0L1,0L1,1Z") == [[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]]


APP = og.ROOT / "app"


def test_hero_rule_matches_the_app():
    import re

    js = (APP / "js" / "select.js").read_text(encoding="utf-8")
    assert int(re.search(r"HERO_MIN_EXCESS = (\d+)", js).group(1)) == og.HERO_MIN_EXCESS
    assert set(re.findall(r"'(\w+)'", re.search(r"STRONG = new Set\(\[(.*?)\]\)", js).group(1))) == og.STRONG_TIERS
