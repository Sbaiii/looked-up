"""Rule constants from config/live.yml, shared with the Cloudflare Worker (ADR 0032)."""

from __future__ import annotations

import os
from pathlib import Path

import yaml


def _find() -> Path:
    here = Path(__file__).resolve()
    for p in (os.environ.get("LIVE_CONFIG"), here.parents[2] / "config" / "live.yml", here.parent / "live.yml"):
        if p and Path(p).exists():
            return Path(p)
    raise FileNotFoundError("config/live.yml not found (set LIVE_CONFIG)")


RULES: dict = yaml.safe_load(_find().read_text())
