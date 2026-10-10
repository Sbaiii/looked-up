"""Which recentchange events count (docs/prereg_phase5.md): our 30 Wikipedias, namespace 0, human edits and page
creations, no maintenance edits. The pattern list is fixed by the pre-registration (config/live.yml)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from lookedup_live.rules import RULES

LANGUAGES: list[str] = json.loads((Path(__file__).parent / "languages.json").read_text())
WIKIS = {f"{code.replace('-', '_')}wiki": code for code in LANGUAGES}

MAINTENANCE = re.compile("|".join(RULES["maintenance_patterns"]), re.IGNORECASE)
REVERT_TAGS = set(RULES["revert_tags"])


def is_maintenance(comment: str | None) -> bool:
    return bool(comment) and bool(MAINTENANCE.search(comment))


def language(event: dict) -> str | None:
    """The language code if the event counts, else None."""
    lang = WIKIS.get(event.get("wiki", ""))
    if lang is None or event.get("namespace") != 0 or event.get("type") not in ("edit", "new") or event.get("bot"):
        return None
    if is_maintenance(event.get("comment")):
        return None
    return lang
