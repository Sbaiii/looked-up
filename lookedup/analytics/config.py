"""Load the pre-registered analytics configuration (config/analytics.yml)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

from lookedup.settings import CONFIG_DIR

ANALYTICS_FILE = CONFIG_DIR / "analytics.yml"
ANALYTICS_V2_FILE = CONFIG_DIR / "analytics_v2.yml"  # Phase 2b additions, read on top (ADR 0019)


@dataclass(frozen=True)
class SpikeParams:
    r1_ratio: float
    r2_ratio: float
    r2_hours: int
    min_views: int
    r3_threshold: float
    mad_scale: float


@dataclass(frozen=True)
class EventParams:
    min_languages: int
    window_hours: int
    breadth_hours: int
    new_event_gap_hours: int
    r3_threshold: float
    single_language_share: float = 0.95


@dataclass(frozen=True)
class AnalyticsConfig:
    raw: dict

    @property
    def period_start(self) -> date:
        return date.fromisoformat(self.raw["period"]["start"])

    @property
    def eval_start(self) -> date:
        return date.fromisoformat(self.raw["period"]["eval_start"])

    @property
    def period_end(self) -> date:
        return date.fromisoformat(self.raw["period"]["end"])

    @property
    def automation(self) -> dict:
        return self.raw["automation"]

    @property
    def baseline(self) -> dict:
        return self.raw["baseline"]

    @property
    def spike(self) -> SpikeParams:
        return SpikeParams(**self.raw["spike"])

    @property
    def event(self) -> EventParams:
        e = self.raw["event"]
        v2 = self.raw.get("v2", {}).get("event", {})
        return EventParams(min_languages=e["min_languages"], window_hours=e["window_hours"],
                           breadth_hours=e["breadth_hours"], new_event_gap_hours=e["new_event_gap_hours"],
                           r3_threshold=self.raw["spike"]["r3_threshold"],
                           single_language_share=v2.get("single_language_share", 0.95))

    def event_variant(self, **changes) -> EventParams:
        """Event parameters with ablation overrides (r3_threshold, min_languages, window_hours)."""
        return replace(self.event, **changes)

    @property
    def min_r3_ablation(self) -> float:
        """Lowest R3 threshold in the ablation grid: spikes are stored down to this score."""
        return min(self.raw["ablations"]["r3_threshold"])


@lru_cache(maxsize=4)
def load(path: Path = ANALYTICS_FILE, v2_path: Path = ANALYTICS_V2_FILE) -> AnalyticsConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if Path(v2_path).exists():
        raw["v2"] = yaml.safe_load(Path(v2_path).read_text(encoding="utf-8")) or {}
    return AnalyticsConfig(raw=raw)
