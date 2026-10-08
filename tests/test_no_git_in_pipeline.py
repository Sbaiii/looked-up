"""Pipelines write to the lake only: no package code or workflow may commit or push to git."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(r"git\s+(commit|push|tag)\b|\bsubprocess\b|\bimport\s+git\b|\bfrom\s+git\s+import|GitPython")


def _files():
    yield from (ROOT / "lookedup").rglob("*.py")
    yield from (ROOT / ".github" / "workflows").glob("*.yml")


def test_pipeline_never_touches_git():
    offenders = [f"{p.relative_to(ROOT)}:{i}: {line.strip()}"
                 for p in _files()
                 for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                 if FORBIDDEN.search(line)]
    assert not offenders, "pipeline code must not run git:\n" + "\n".join(offenders)


def test_workflows_cannot_write_to_the_repo():
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = wf.read_text(encoding="utf-8")
        assert "contents: write" not in text, wf.name
        assert re.search(r"permissions:\s*\n\s*contents:\s*read", text), f"{wf.name} must declare contents: read"
