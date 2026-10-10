"""Which recentchange events count (docs/prereg_phase5.md): our 30 Wikipedias, namespace 0, human edits and page
creations, no maintenance edits. The pattern list is fixed by the pre-registration."""

from __future__ import annotations

import json
import re
from pathlib import Path

LANGUAGES: list[str] = json.loads((Path(__file__).parent / "languages.json").read_text())
WIKIS = {f"{code.replace('-', '_')}wiki": code for code in LANGUAGES}

MAINTENANCE = re.compile(
    r"\brevert|\bundo\b|\bundid\b|\brollback\b|^rv\b|\brv\s|reverted edits|undid revision|"
    r"\bAWB\b|\bHotCat\b|\bTwinkle\b|\bhuggle\b|\bIABot\b|InternetArchiveBot|\bWPCleaner\b|"
    r"^\s*\{\{[^}]*\}\}\s*$|\btypos?\b|fix typo|copyedit",
    re.IGNORECASE,
)
REVERT_TAGS = {"mw-reverted", "mw-rollback", "mw-undo", "mw-manual-revert"}


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
