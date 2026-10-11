"""The analytics configuration as loaded from config/ (read only: the pre-registered files are never changed)."""
from __future__ import annotations

from lookedup.analytics.config import load


def test_event_variant_changes_only_what_it_is_given():
    cfg = load()
    v = cfg.event_variant(min_languages=5)
    assert v.min_languages == 5
    assert v.window_hours == cfg.event.window_hours and v.r3_threshold == cfg.event.r3_threshold


def test_spikes_are_stored_down_to_the_lowest_ablation_threshold():
    cfg = load()
    assert cfg.min_r3_ablation == min(cfg.raw["ablations"]["r3_threshold"])
    assert cfg.min_r3_ablation <= cfg.spike.r3_threshold


def test_period_end_override_only_when_set(monkeypatch):
    cfg = load()
    monkeypatch.delenv("LOOKEDUP_PERIOD_END", raising=False)
    registered = cfg.period_end
    assert registered.isoformat() == cfg.raw["period"]["end"]
    monkeypatch.setenv("LOOKEDUP_PERIOD_END", "2026-12-31")
    assert cfg.period_end.isoformat() == "2026-12-31"
    assert cfg.eval_start < registered


def test_tiers_run_from_widest_to_narrowest():
    tiers = load().tiers
    assert [name for name, _ in tiers] == ["planetary", "international", "noticed"]
    assert [n for _, n in tiers] == sorted((n for _, n in tiers), reverse=True)


def test_product_events_need_two_languages_and_keep_the_rest():
    cfg = load()
    assert cfg.product_event.min_languages == 2                      # ADR 0021
    assert cfg.event.min_languages == 3                              # the pre-registered rule is untouched
    assert cfg.product_event.window_hours == cfg.event.window_hours


def test_dbt_vars_carry_the_period_thresholds_and_languages():
    from lookedup.languages import active_codes
    from lookedup.warehouse import dbt_vars

    v = dbt_vars("/tmp/lake")
    cfg = load()
    assert v["lake_root"] == "/tmp/lake"
    assert v["period_start"] == f"{cfg.period_start:%Y-%m-%d}"
    assert v["r3_threshold"] == cfg.spike.r3_threshold
    assert v["languages"] == active_codes() and len(v["languages"]) == 30
