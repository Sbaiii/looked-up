"""The analytics configuration as loaded from config/ (read only: the pre-registered files are never changed)."""
from __future__ import annotations

from lookedup.analytics.config import load


def test_event_variant_changes_only_what_it_is_given():
    cfg = load()
    v = cfg.event_variant(min_languages=5)
    assert v.min_languages == 5
    assert v.window_hours == cfg.event.window_hours and v.r3_threshold == cfg.event.r3_threshold
